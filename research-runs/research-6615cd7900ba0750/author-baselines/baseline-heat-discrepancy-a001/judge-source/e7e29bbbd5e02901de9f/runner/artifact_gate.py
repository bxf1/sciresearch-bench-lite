"""No untrusted code executes here: only bounded numeric artifacts are admitted."""
from __future__ import annotations
import io
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import zipfile
import numpy as np
from .common import read_json, file_hash

MAX_OUTPUT = 256 * 1024**2
MAX_SOURCE = 20 * 1024**2
MAX_FILES = 1000
MAX_ENTRIES = 2000
MAX_DEPTH = 32
OUTPUT_NAMES = {"heat": "u0.npy", "ode": "model.json", "poisson": "solution.npy"}

class ArtifactError(ValueError):
    pass

def safe_relative(value):
    if not isinstance(value, str) or "\x00" in value:
        raise ArtifactError("path must be a NUL-free string")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(x in (".", "..", "") for x in value.split("/")) or "\\" in value:
        raise ArtifactError("unsafe path")
    return path

def regular_tree(root, max_bytes=MAX_OUTPUT, max_files=MAX_FILES):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ArtifactError("root must be a real directory")
    files, total, entries = [], 0, 0
    def visit(directory, depth):
        nonlocal entries, total
        with os.scandir(directory) as listing:
            for item in listing:
                p = Path(directory) / item.name
                entries += 1
                if entries > MAX_ENTRIES or depth >= MAX_DEPTH:
                    raise ArtifactError("tree entry/depth quota exceeded")
                info = item.stat(follow_symlinks=False)
                safe_relative(p.relative_to(root).as_posix())
                if stat.S_ISDIR(info.st_mode):
                    visit(p, depth + 1)
                    continue
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ArtifactError("links and special files are forbidden")
                total += info.st_size
                files.append(p)
                if total > max_bytes or len(files) > max_files:
                    raise ArtifactError("tree quota exceeded")
    visit(root, 0)
    return files

def snapshot_source(workspace, relative_source, destination):
    """Copy from held directory descriptors; no source path component follows links.

    O_NONBLOCK prevents a raced FIFO open from hanging. Each file is checked after
    open and after a bounded copy, so growth cannot fill host storage. A directory
    rename cannot redirect traversal once its descriptor has been acquired.
    """
    relative = safe_relative(relative_source)
    workspace = Path(workspace)
    if not workspace.is_absolute():
        raise ArtifactError("workspace must be an absolute canonical path")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    current = os.open("/", flags)
    destination = Path(destination)
    total = files = entries = 0
    has_entrypoint = False

    def visit(directory_fd, target, depth):
        nonlocal total, files, entries, has_entrypoint
        if depth > MAX_DEPTH:
            raise ArtifactError("source depth quota exceeded")
        with os.scandir(directory_fd) as listing:
            for item in listing:
                entries += 1
                if entries > MAX_ENTRIES:
                    raise ArtifactError("source entry quota exceeded")
                safe_relative(item.name)
                before = os.stat(item.name, dir_fd=directory_fd, follow_symlinks=False)
                dest = target / item.name
                if stat.S_ISDIR(before.st_mode):
                    child = os.open(item.name, flags, dir_fd=directory_fd)
                    try:
                        held = os.fstat(child)
                        if (held.st_dev, held.st_ino) != (before.st_dev, before.st_ino):
                            raise ArtifactError("source directory changed during snapshot")
                        dest.mkdir()
                        visit(child, dest, depth + 1)
                    finally:
                        os.close(child)
                    continue
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                    raise ArtifactError("source links and special files are forbidden")
                files += 1
                if files > MAX_FILES or before.st_size > MAX_SOURCE - total:
                    raise ArtifactError("source quota exceeded")
                fd = os.open(item.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
                try:
                    held = os.fstat(fd)
                    if not stat.S_ISREG(held.st_mode) or held.st_nlink != 1 or (held.st_dev, held.st_ino) != (before.st_dev, before.st_ino):
                        raise ArtifactError("source file changed or became special during snapshot")
                    if held.st_size > MAX_SOURCE - total:
                        raise ArtifactError("source quota exceeded")
                    copied = 0
                    with dest.open("xb") as out:
                        while True:
                            chunk = os.read(fd, min(1024 * 1024, MAX_SOURCE - total + 1))
                            if not chunk:
                                break
                            total += len(chunk)
                            copied += len(chunk)
                            if total > MAX_SOURCE or copied > held.st_size:
                                raise ArtifactError("source grew during snapshot or exceeded quota")
                            out.write(chunk)
                    after = os.fstat(fd)
                    signature = lambda s: (s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)
                    if copied != held.st_size or signature(after) != signature(held):
                        raise ArtifactError("source changed during snapshot")
                finally:
                    os.close(fd)
                if depth == 0 and item.name == "solve.py":
                    has_entrypoint = True

    try:
        for name in (*workspace.parts[1:], *relative.parts):
            next_fd = os.open(name, flags, dir_fd=current)
            os.close(current)
            current = next_fd
        destination.mkdir(parents=True, exist_ok=False)
        visit(current, destination, 0)
        if not has_entrypoint:
            raise ArtifactError("missing solve.py")
    finally:
        os.close(current)

def _array_header(stream, size):
    version = np.lib.format.read_magic(stream)
    if version == (1, 0):
        shape, order, dtype = np.lib.format.read_array_header_1_0(stream)
    elif version == (2, 0):
        shape, order, dtype = np.lib.format.read_array_header_2_0(stream)
    else:
        raise ArtifactError("unsupported NPY format")
    if len(shape) > MAX_DEPTH or any(type(n) is not int or n < 0 for n in shape):
        raise ArtifactError("invalid NPY dimensions")
    if dtype.hasobject or dtype.kind not in "fiubS":
        raise ArtifactError("unsafe NPY dtype")
    if math.prod(shape) * dtype.itemsize + stream.tell() != size:
        raise ArtifactError("NPY payload size mismatch")
    return shape, order, dtype

def load_npy(path, shape):
    path = Path(path)
    if path.stat().st_size > MAX_OUTPUT:
        raise ArtifactError("oversized NPY")
    with path.open("rb") as stream:
        actual, order, dtype = _array_header(stream, path.stat().st_size)
        if tuple(actual) != tuple(shape) or dtype.str != "<f8" or dtype.hasobject:
            raise ArtifactError("NPY shape/dtype mismatch")
    arr = np.load(path, allow_pickle=False)
    if not np.isfinite(arr).all():
        raise ArtifactError("nonfinite NPY")
    return arr

def load_model(path):
    if Path(path).stat().st_size > 65536:
        raise ArtifactError("oversized model")
    model = read_json(path)
    if not isinstance(model, dict) or set(model) != {"coefficients"}:
        raise ArtifactError("model keys must be exactly coefficients")
    values = model["coefficients"]
    if not isinstance(values, list) or len(values) != 10 or any(not isinstance(row,list) or len(row)!=2 for row in values):
        raise ArtifactError("model shape mismatch")
    if any(type(x) not in (int,float) for row in values for x in row):
        raise ArtifactError("model coefficients must be numeric")
    try:
        arr = np.asarray(values, dtype=np.float64)
    except (OverflowError, ValueError) as exc:
        raise ArtifactError("model cannot be represented as binary64") from exc
    if not np.isfinite(arr).all():
        raise ArtifactError("nonfinite model")
    return arr

def check_npz(path, max_bytes=MAX_OUTPUT):
    """Bound expansion before loading numeric NPZ (including sparse format bytes)."""
    total = 0
    with zipfile.ZipFile(path) as archive:
        names = set()
        for item in archive.infolist():
            safe_relative(item.filename)
            if stat.S_ISLNK(item.external_attr >> 16):
                raise ArtifactError("NPZ links are forbidden")
            if item.filename in names or not item.filename.endswith(".npy"):
                raise ArtifactError("unexpected NPZ member")
            names.add(item.filename)
            total += item.file_size
            if total > max_bytes or len(names) > MAX_FILES:
                raise ArtifactError("NPZ expansion quota exceeded")
        for item in archive.infolist():
            with archive.open(item) as f:
                payload = f.read(item.file_size + 1)
            if len(payload) != item.file_size:
                raise ArtifactError("NPZ member size mismatch")
            buf = io.BytesIO(payload)
            shape, order, dtype = _array_header(buf, len(payload))
            if dtype.kind == "S" and not (item.filename == "format.npy" and shape == () and dtype.itemsize <= 16):
                raise ArtifactError("nonnumeric NPZ")
            buf.seek(0)
            arr = np.load(buf, allow_pickle=False)
            if arr.dtype.hasobject or arr.dtype.kind == "c":
                raise ArtifactError("unsafe NPZ dtype")
            if arr.dtype.kind in "fiub" and not np.isfinite(arr).all():
                raise ArtifactError("nonfinite NPZ")
            if arr.dtype.kind not in "fiub" and not (item.filename == "format.npy" and arr.dtype.kind == "S"):
                raise ArtifactError("nonnumeric NPZ")

def extract_tar(stream, target, max_bytes=MAX_OUTPUT, max_files=MAX_FILES):
    """Extract docker cp stream without tar.extract(), links, or traversal."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=False)
    seen, materialized, total, count = set(), set(), 0, 0
    def ensure_directory(parts):
        for index in range(1, len(parts) + 1):
            key = "/".join(parts[:index])
            if key not in materialized:
                if len(materialized) >= MAX_ENTRIES:
                    raise ArtifactError("archive entry quota exceeded")
                target.joinpath(*parts[:index]).mkdir()
                materialized.add(key)
    class BoundedStream:
        # docker cp emits uncompressed tar. Bound PAX/header reads as well as data.
        remaining = max_bytes + MAX_ENTRIES * 10240
        def read(self, size=-1):
            if size < 0 or size > self.remaining:
                raise ArtifactError("tar stream quota exceeded")
            data = stream.read(size)
            self.remaining -= len(data)
            return data
    with tarfile.open(fileobj=BoundedStream(), mode="r|") as archive:
        for member in archive:
            name = member.name.rstrip("/")
            # docker cp /output/. emits the directory prefix './'.
            if name in (".", "") and member.isdir():
                continue
            if name.startswith("./"):
                name = name[2:]
            relative = safe_relative(name)
            if len(relative.parts) > MAX_DEPTH or len(seen) >= MAX_ENTRIES:
                raise ArtifactError("archive entry/depth quota exceeded")
            if name in seen:
                raise ArtifactError("duplicate tar path")
            seen.add(name)
            path = target.joinpath(*relative.parts)
            if member.isdir():
                ensure_directory(relative.parts)
                continue
            if not member.isfile():
                raise ArtifactError("tar link or special file")
            count += 1
            total += member.size
            if count > max_files or total > max_bytes:
                raise ArtifactError("archive quota exceeded")
            ensure_directory(relative.parts[:-1])
            if name in materialized or len(materialized) >= MAX_ENTRIES:
                raise ArtifactError("archive duplicate or entry quota exceeded")
            materialized.add(name)
            source = archive.extractfile(member)
            with path.open("xb") as dest:
                shutil.copyfileobj(source, dest, length=1024*1024)

def admit_outputs(task, input_root, output_root, destination):
    """Returns per-case validity; unexpected paths reject the entire submission."""
    manifest = read_json(Path(input_root) / "manifest.json")
    entries = manifest["cases"]
    filename = OUTPUT_NAMES[task]
    allowed = {f"cases/{e['id']}/{filename}" for e in entries}
    files = regular_tree(output_root)
    if any(p.relative_to(output_root).as_posix() not in allowed for p in files):
        raise ArtifactError("output filename not allowlisted")
    allowed_dirs = {"cases", *(f"cases/{e['id']}" for e in entries)}
    for directory, dirs, names in os.walk(output_root):
        if any((Path(directory) / d).relative_to(output_root).as_posix() not in allowed_dirs for d in dirs):
            raise ArtifactError("output directory not allowlisted")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    rows = []
    for entry in entries:
        rel = f"cases/{entry['id']}/{filename}"
        source = Path(output_root) / rel
        try:
            if task == "ode":
                load_model(source)
            else:
                n = read_json(Path(input_root) / entry["path"] / "metadata.json").get("n")
                shape = (256,) if task == "heat" else (n*n, 4)
                load_npy(source, shape)
            dest = destination / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
            dest.chmod(0o444)
            rows.append({"id":entry["id"], "artifact_valid":True, "sha256":file_hash(dest)})
        except (ValueError, OSError, OverflowError, TypeError) as exc:
            rows.append({"id":entry["id"], "artifact_valid":False, "reason":str(exc)})
    for directory, dirs, names in os.walk(destination, topdown=False):
        Path(directory).chmod(0o555)
    return rows
