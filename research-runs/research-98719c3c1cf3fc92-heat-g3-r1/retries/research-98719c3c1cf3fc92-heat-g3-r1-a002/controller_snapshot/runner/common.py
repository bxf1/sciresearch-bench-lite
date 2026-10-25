"""Small deterministic serialization and provenance utilities."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

VERSION = "0.3.0"
TASKS = ("heat", "ode", "poisson")

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def digest(data):
    return hashlib.sha256(data).hexdigest()

def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)

def read_json(path):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"duplicate JSON key: {key}")
            out[key] = value
        return out
    def invalid(value):
        raise ValueError(f"invalid JSON numeric constant: {value}")
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=invalid)

def tree_hashes(path):
    root = Path(path)
    return {p.relative_to(root).as_posix(): file_hash(p) for p in sorted(root.rglob("*")) if p.is_file()}
