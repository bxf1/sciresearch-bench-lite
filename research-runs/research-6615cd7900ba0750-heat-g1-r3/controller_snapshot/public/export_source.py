"""Root-owned R source exporter; writes only an uncompressed bounded tar stream.

Install at /opt/bench/export_source.py with trusted runner/__init__.py,
runner/artifact_gate.py and runner/common.py under /opt/bench/trusted. Create /run/bench-export owned by root,
mode 0700. The research user must have no sudo or container-management access.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tarfile
import tempfile

sys.path.insert(0, "/opt/bench/trusted")
from runner.artifact_gate import snapshot_source


def export(relative_source, stream, *, workspace=Path("/workspace"), staging=Path("/run/bench-export")):
    if os.geteuid() != 0:
        raise PermissionError("source export requires trusted root execution")
    staging = Path(staging)
    info = staging.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077:
        raise PermissionError("export staging must be a root-owned private directory")
    with tempfile.TemporaryDirectory(prefix="snapshot-", dir=staging) as temporary:
        snapshot = Path(temporary) / "source"
        snapshot_source(workspace, relative_source, snapshot)
        with tarfile.open(fileobj=stream, mode="w|", format=tarfile.PAX_FORMAT) as archive:
            archive.add(snapshot, arcname=".", recursive=True)


def main():
    raw = sys.stdin.buffer.read(4097)
    if len(raw) > 4096:
        raise ValueError("source export request exceeds 4096 bytes")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate export request key")
            result[key] = value
        return result
    request = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(request, dict) or set(request) != {"source"} or not isinstance(request["source"], str):
        raise ValueError("export accepts only a relative source string")
    export(request["source"], sys.stdout.buffer)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__ + ": " + str(exc)[:1024]}), file=sys.stderr)
        raise SystemExit(2)
