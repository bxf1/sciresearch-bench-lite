"""Root-owned R helper for a fixed request/response directory protocol.

Install read-only at /opt/bench/bridge_io.py and invoke with python -I. The CLI
never accepts a directory path; optional function roots exist only for unit tests.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import stat
import sys

WORKSPACE = Path("/workspace")
MAX_REQUEST = 4096
MAX_RESPONSE = 65536
MAX_PENDING = 64
REQUEST_ID = re.compile(r"[0-9a-f]{32}\Z")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def parse_json(payload):
    def invalid(value):
        raise ValueError("nonfinite JSON constant")
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("nonfinite JSON number")
        return result
    return json.loads(payload, object_pairs_hook=_pairs, parse_constant=invalid, parse_float=finite_float)


def validate_request(value, request_id=None):
    if not isinstance(value, dict) or value.get("version") != 1 or type(value.get("version")) is not int:
        raise ValueError("unsupported request version")
    identifier = value.get("request_id")
    if not isinstance(identifier, str) or REQUEST_ID.fullmatch(identifier) is None or (request_id is not None and identifier != request_id):
        raise ValueError("invalid request ID")
    operation = value.get("operation")
    field = {"evaluate": "source", "finalize": "candidate_id"}.get(operation)
    if field is None or set(value) != {"version", "request_id", "operation", field}:
        raise ValueError("unknown operation or request fields")
    if not isinstance(value[field], str) or not value[field] or len(value[field]) > 1024 or "\x00" in value[field]:
        raise ValueError("invalid request value")
    return value


def open_protocol_directory(workspace, leaf):
    """Pin every ancestor with a descriptor; never follow an R-controlled link."""
    workspace = Path(workspace)
    if not workspace.is_absolute() or leaf not in ("requests", "responses"):
        raise ValueError("invalid protocol directory")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    current = os.open("/", flags)
    try:
        for name in (*workspace.parts[1:], ".bench", leaf):
            child = os.open(name, flags, dir_fd=current)
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


def read_requests(workspace=WORKSPACE):
    try:
        directory = open_protocol_directory(workspace, "requests")
    except FileNotFoundError:
        return []
    result = []
    try:
        with os.scandir(directory) as listing:
            for scanned, item in enumerate(listing):
                if scanned >= 256 or len(result) >= MAX_PENDING:
                    break
                if not item.name.endswith(".json") or REQUEST_ID.fullmatch(item.name[:-5]) is None:
                    continue
                identifier = item.name[:-5]
                try:
                    fd = os.open(item.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                    try:
                        info = os.fstat(fd)
                        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_REQUEST:
                            raise ValueError("request must be a regular unlinked file <=4096 bytes")
                        payload = os.read(fd, MAX_REQUEST + 1)
                        if len(payload) != info.st_size or len(payload) > MAX_REQUEST:
                            raise ValueError("request changed or exceeded size limit")
                    finally:
                        os.close(fd)
                    request = validate_request(parse_json(payload), identifier)
                    result.append({"request_id": identifier, "request": request})
                except (OSError, ValueError, UnicodeError) as exc:
                    result.append({"request_id": identifier, "error": str(exc)[:512]})
    finally:
        os.close(directory)
    return result


def write_response(request_id, response, workspace=WORKSPACE):
    if not isinstance(request_id, str) or REQUEST_ID.fullmatch(request_id) is None:
        raise ValueError("invalid response request ID")
    if not isinstance(response, dict) or response.get("request_id") != request_id:
        raise ValueError("response/request mismatch")
    payload = json.dumps(response, separators=(",", ":"), allow_nan=False).encode()
    if len(payload) > MAX_RESPONSE:
        raise ValueError("response exceeds 64 KiB")
    directory = open_protocol_directory(workspace, "responses")
    temporary = request_id + ".host-tmp"
    try:
        owner = os.fstat(directory)
        if owner.st_uid != os.geteuid() or stat.S_IMODE(owner.st_mode) & 0o022:
            raise PermissionError("response directory must be owned by the trusted executor and not group/world-writable")
        # Never replace an R-created file/link. A hostile R can deny its own
        # feedback, but cannot redirect a privileged write outside this directory.
        try:
            info = os.stat(request_id + ".json", dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
                raise ValueError("unsafe existing response")
            fd = os.open(request_id + ".json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                if os.read(fd, MAX_RESPONSE + 1) != payload:
                    raise ValueError("existing response differs from trusted decision")
            finally:
                os.close(fd)
            return  # Safe retry after publication succeeded but host acknowledgement did not.
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            # link() is an atomic no-overwrite publish, with both paths relative
            # to the same held directory descriptor. It never follows the target.
            os.link(temporary, request_id + ".json", src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
    finally:
        os.close(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("poll", "respond"))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise PermissionError("trusted bridge helper requires root execution")
    if args.operation == "poll":
        print(json.dumps(read_requests(), separators=(",", ":"), allow_nan=False))
    else:
        payload = sys.stdin.buffer.read(MAX_RESPONSE + 4097)
        if len(payload) > MAX_RESPONSE + 4096:
            raise ValueError("response envelope too large")
        envelope = parse_json(payload)
        if not isinstance(envelope, dict) or set(envelope) != {"request_id", "response"}:
            raise ValueError("invalid response envelope")
        write_response(envelope["request_id"], envelope["response"])
        print('{"written":true}')


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__ + ": " + str(exc)[:1024]}), file=sys.stderr)
        raise SystemExit(2)
