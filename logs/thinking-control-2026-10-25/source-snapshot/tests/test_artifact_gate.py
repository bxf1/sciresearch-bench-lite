"""Bounded parsing and archive traversal regression tests."""
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from scipy.sparse import eye, save_npz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runner import artifact_gate as gate


class ArtifactGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_bad_paths(self):
        for path in ("", "/abs", "../x", "x/../y", "x//y", "x\\y", "./x", "a\x00b", None):
            with self.subTest(path=path), self.assertRaises(gate.ArtifactError):
                gate.safe_relative(path)

    def test_valid_npy_and_shape_dtype_nonfinite_rejections(self):
        path = self.base / "a.npy"
        np.save(path, np.zeros(256, dtype="<f8"), allow_pickle=False)
        self.assertEqual(gate.load_npy(path, (256,)).shape, (256,))
        for value in (np.zeros(255), np.zeros(256, dtype=np.float32), np.zeros(256, dtype=">f8"), np.full(256, np.inf), np.zeros(256, dtype=complex)):
            np.save(path, value, allow_pickle=False)
            with self.assertRaises(ValueError):
                gate.load_npy(path, (256,))

    def test_json_duplicate_nan_shape_and_huge_integer(self):
        path = self.base / "model.json"
        valid = {"coefficients": np.zeros((10, 2)).tolist()}
        path.write_text(json.dumps(valid))
        self.assertEqual(gate.load_model(path).shape, (10, 2))
        bad = ['{"coefficients":[],"coefficients":[]}', '{"coefficients":NaN}', '{"coefficients":[]}', json.dumps({"coefficients": [[10**400, 0]] * 10}), json.dumps({"coefficients": [[True, 0]] * 10})]
        for payload in bad:
            path.write_text(payload)
            with self.assertRaises(ValueError):
                gate.load_model(path)

    def test_npz_object_complex_and_compression_bomb(self):
        path = self.base / "a.npz"
        for array in (np.array([object()], dtype=object), np.zeros(4, dtype=complex)):
            np.savez(path, data=array)
            with self.assertRaises(ValueError):
                gate.check_npz(path)
        np.savez_compressed(path, data=np.zeros(100_000))
        self.assertLess(path.stat().st_size, 2048)
        with self.assertRaisesRegex(gate.ArtifactError, "expansion"):
            gate.check_npz(path, max_bytes=4096)

    def test_npz_forged_huge_shape_rejected_before_numpy_load(self):
        payload = io.BytesIO()
        np.lib.format.write_array_header_1_0(payload, {"descr": "<f8", "fortran_order": False, "shape": (10**12,)})
        path = self.base / "huge.npz"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("data.npy", payload.getvalue())
        with patch("runner.artifact_gate.np.load", side_effect=AssertionError("must not allocate")):
            with self.assertRaisesRegex(gate.ArtifactError, "payload"):
                gate.check_npz(path)

    def test_sparse_npz_is_accepted(self):
        path = self.base / "A.npz"
        save_npz(path, eye(4, format="csr"))
        gate.check_npz(path)

    def test_tree_symlinks_hardlinks_special_files_and_many_directories(self):
        root = self.base / "tree"
        root.mkdir()
        outside = self.base / "sentinel"
        outside.write_text("private")
        (root / "link").symlink_to(outside)
        with self.assertRaises(gate.ArtifactError):
            gate.regular_tree(root)
        (root / "link").unlink()
        os.link(outside, root / "hardlink")
        with self.assertRaises(gate.ArtifactError):
            gate.regular_tree(root)
        (root / "hardlink").unlink()
        os.mkfifo(root / "fifo")
        with self.assertRaises(gate.ArtifactError):
            gate.regular_tree(root)
        (root / "fifo").unlink()
        for index in range(6):
            (root / str(index)).mkdir()
        with patch.object(gate, "MAX_ENTRIES", 5), self.assertRaisesRegex(gate.ArtifactError, "entry"):
            gate.regular_tree(root)

    def archive(self, members):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            for name, kind, payload in members:
                member = tarfile.TarInfo(name)
                member.type = kind
                if kind == tarfile.REGTYPE:
                    member.size = len(payload)
                    archive.addfile(member, io.BytesIO(payload))
                else:
                    member.linkname = "outside"
                    archive.addfile(member)
        stream.seek(0)
        return stream

    def test_tar_valid_and_traversal_links_duplicates(self):
        stream = self.archive([("./cases/a/u0.npy", tarfile.REGTYPE, b"example")])
        gate.extract_tar(stream, self.base / "valid")
        self.assertEqual((self.base / "valid/cases/a/u0.npy").read_bytes(), b"example")
        cases = [[("../escape", tarfile.REGTYPE, b"x")], [("link", tarfile.SYMTYPE, b"")], [("a", tarfile.REGTYPE, b"x"), ("a", tarfile.REGTYPE, b"y")]]
        for index, members in enumerate(cases):
            with self.assertRaises(gate.ArtifactError):
                gate.extract_tar(self.archive(members), self.base / f"bad-{index}")

    def test_tar_counts_implicit_and_empty_directories(self):
        members = [(f"a{i}/b/c/file", tarfile.REGTYPE, b"x") for i in range(4)]
        with patch.object(gate, "MAX_ENTRIES", 6), self.assertRaisesRegex(gate.ArtifactError, "entry"):
            gate.extract_tar(self.archive(members), self.base / "implicit")
        empty = [(str(i), tarfile.DIRTYPE, b"") for i in range(7)]
        with patch.object(gate, "MAX_ENTRIES", 6), self.assertRaisesRegex(gate.ArtifactError, "entry"):
            gate.extract_tar(self.archive(empty), self.base / "empty")

    def test_output_allowlist_and_missing_case_denominator(self):
        inputs = self.base / "inputs"
        inputs.mkdir()
        (inputs / "manifest.json").write_text(json.dumps({"cases": [{"id": "a", "path": "a"}, {"id": "b", "path": "b"}]}))
        for case in ("a", "b"):
            (inputs / case).mkdir()
            (inputs / case / "metadata.json").write_text("{}")
        outputs = self.base / "outputs"
        (outputs / "cases/a").mkdir(parents=True)
        np.save(outputs / "cases/a/u0.npy", np.zeros(256), allow_pickle=False)
        rows = gate.admit_outputs("heat", inputs, outputs, self.base / "admitted")
        self.assertEqual([row["artifact_valid"] for row in rows], [True, False])
        (outputs / "reward.json").write_text('{"reward":1}')
        with self.assertRaisesRegex(gate.ArtifactError, "allowlisted"):
            gate.admit_outputs("heat", inputs, outputs, self.base / "forged")


if __name__ == "__main__":
    unittest.main()
