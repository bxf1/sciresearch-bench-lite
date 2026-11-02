"""Read-only checks for the published nine-group results and evidence archive."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "data/r1-complete-20261101"


def digest(stream):
    h = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    publication = json.loads((META / "publication.json").read_text())
    analysis = json.loads((ROOT / "results/r1-complete-20261101/analysis.json").read_text())
    readme = (ROOT / "README.md").read_text()
    assert analysis["reported_groups"] == len(analysis["rows"]) == 9
    assert analysis["scientific_sessions"] == 10 and analysis["data_instances"] == 162
    for task, label in (("heat", "Heat"), ("ode", "ODE"), ("poisson", "Poisson")):
        rows = sorted((r for r in analysis["rows"] if r["task"] == task), key=lambda r: r["group"])
        assert "| " + label + " | " + " | ".join(f"{r['final_score']:.3f}" for r in rows) + " |" in readme
        assert all(r["reward"] == 1 and r["main_numeric"]["final"]["overall"]["passed_per_replay"] == [12, 12, 12] for r in rows)
    for report in (ROOT / "README.md", ROOT / "docs/r1-complete-report-20261101.md", ROOT / "docs/r1-complete-publication-20261102.md"):
        for link in re.findall(r"\]\(([^)]+)\)", report.read_text()):
            if not link.startswith(("https:", "http:", "#")):
                assert (report.parent / link).resolve().exists(), (report, link)
    pdf = ROOT / publication["report"]["path"]
    with pdf.open("rb") as stream:
        assert digest(stream) == publication["report"]["sha256"]
    summary = {"status": "passed", "reported_groups": 9, "scientific_sessions": 10,
               "instances": 162, "readme_matches_results": True, "report_hash_verified": True}
    if args.archive:
        assert args.archive.stat().st_size == publication["archive"]["bytes"]
        with args.archive.open("rb") as stream:
            assert digest(stream) == publication["archive"]["sha256"]
        manifest_bytes = (META / "archive-manifest.json").read_bytes()
        manifest = json.loads(manifest_bytes)
        prefix = manifest["archive_prefix"] + "/"
        expected = {prefix + r["path"]: r for r in manifest["files"]}
        observed = {}
        source_manifests = []
        internal_manifest = None
        with tarfile.open(args.archive, "r|gz") as archive:
            for member in archive:
                assert member.name.startswith(prefix) and ".." not in Path(member.name).parts
                assert member.name not in observed, member.name
                if member.name == prefix + "PUBLICATION-MANIFEST.json":
                    assert member.isfile()
                    internal_manifest = archive.extractfile(member).read()
                    continue
                row = expected[member.name]
                if member.islnk():
                    assert member.linkname in observed, member.linkname
                    size, sha = observed[member.linkname]
                else:
                    assert member.isfile(), member.name
                    size = member.size
                    stream = archive.extractfile(member)
                    if member.name.endswith("/delivery-manifest.json"):
                        content = stream.read()
                        sha = hashlib.sha256(content).hexdigest()
                        source_manifests.append(json.loads(content))
                    else:
                        sha = digest(stream)
                assert size == row["bytes"] and sha == row["sha256"], member.name
                observed[member.name] = (size, sha)
        assert internal_manifest == manifest_bytes
        assert set(observed) == set(expected)
        for source in source_manifests:
            for row in source["files"]:
                assert observed[prefix + row["path"]] == (row["bytes"], row["sha256"])
        assert len(source_manifests) == 3
        summary.update(archive_files_verified=len(observed), original_manifests_verified=3)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
