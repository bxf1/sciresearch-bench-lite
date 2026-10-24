#!/usr/bin/env python3
"""Research-side file bridge client. No network or host credentials are needed."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
import uuid

BRIDGE_ROOT = Path("/workspace/.bench")
MAX_REQUEST = 4096
MAX_RESPONSE = 65536


def submit(action, value, *, root=BRIDGE_ROOT, timeout=1800.0, interval=.1):
    if action not in ("evaluate", "finalize") or not isinstance(value, str) or not value or len(value) > 1024:
        raise ValueError("expected evaluate <relative-source-dir> or finalize <candidate-id>")
    request_id = uuid.uuid4().hex
    request = {"version": 1, "request_id": request_id, "operation": action,
               "source" if action == "evaluate" else "candidate_id": value}
    encoded = json.dumps(request, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > MAX_REQUEST:
        raise ValueError("request exceeds 4096 bytes")
    root = Path(root)
    requests, responses = root / "requests", root / "responses"
    requests.mkdir(parents=True, exist_ok=True)
    responses.mkdir(parents=True, exist_ok=True)
    temporary = requests / (request_id + ".tmp")
    with temporary.open("xb") as stream:
        os.fchmod(stream.fileno(), 0o644)
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.rename(requests / (request_id + ".json"))
    deadline = time.monotonic() + timeout
    response_path = responses / (request_id + ".json")
    while time.monotonic() < deadline:
        if response_path.is_file():
            with response_path.open("rb") as stream:
                payload = stream.read(MAX_RESPONSE + 1)
            if len(payload) > MAX_RESPONSE:
                raise ValueError("response exceeds 64 KiB")
            response = json.loads(payload)
            if not isinstance(response, dict) or response.get("request_id") != request_id:
                raise ValueError("response/request mismatch")
            return response
        time.sleep(min(interval, max(0, deadline - time.monotonic())))
    raise TimeoutError("host response deadline exceeded; research budget is enforced by the host")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("evaluate", "finalize"))
    parser.add_argument("value")
    args = parser.parse_args()
    try:
        response = submit(args.action, args.value)
        print(json.dumps(response, allow_nan=False))
    except (ValueError, OSError, TimeoutError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        raise SystemExit(1)
    if not response.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
