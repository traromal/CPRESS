import json
from pathlib import Path

import cpress.archive as ar


def _mk_files(tmp: Path) -> Path:
    root = tmp / "src"
    (root / "sub").mkdir(parents=True)
    (root / "hello.txt").write_text("hello", encoding="utf-8")
    (root / "sub" / "deep.txt").write_text("inside", encoding="utf-8")
    return root


def test_tar_gz_roundtrip(tmp_path: Path):
    src = _mk_files(tmp_path)
    out = tmp_path / "out.tar.gz"
    ar.compress([src], out, "tar.gz", level=6, exclude=[], password=None, zip_aes=True, progress_cb=None)
    dest = tmp_path / "extracted"
    ar.decompress(out, dest, "tar.gz", password=None)
    assert (dest / src.name / "hello.txt").read_text() == "hello"
    assert (dest / src.name / "sub" / "deep.txt").read_text() == "inside"


def test_zip_list_and_manifest(tmp_path: Path):
    src = _mk_files(tmp_path)
    out = tmp_path / "out.zip"
    ar.compress([src], out, "zip", level=6, exclude=[], password=None, zip_aes=True, progress_cb=None)
    entries = ar.list_archive(out, "zip", password=None)
    names = {e.name for e in entries}
    assert f"{src.name}/hello.txt" in names
    manifest = ar.build_manifest([src], [])
    live = ar.hash_archive(out, "zip", password=None)
    assert manifest["hash"] == live["hash"] == "sha256"
    for k, v in manifest["entries"].items():
        assert live["entries"].get(k) == v
