"""Quick fuzz harness for archive parsing."""
from __future__ import annotations

import random
import shutil
import sys
import tempfile
from pathlib import Path

from cpress import archive

FORMATS = ["zip", "tar.gz", "tar.bz2", "tar.xz", "tar.zst"]


def fuzz_once(data: bytes, fmt: str, workdir: Path) -> None:
    target = workdir / f"fuzz.{fmt.replace('.', '')}"
    target.write_bytes(data)
    try:
        archive.list_archive(target, fmt, password=None)
    except Exception:
        pass
    try:
        archive.test_archive(target, fmt, password=None)
    except Exception:
        pass


def main(count: int = 100) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        for i in range(count):
            fmt = random.choice(FORMATS)
            size = random.randint(1, 1024 * 10)
            fuzz = random.randbytes(size)
            fuzz_once(fuzz, fmt, workdir)
    print("Fuzz run complete")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fuzz archive parsing")
    parser.add_argument("--count", type=int, default=100)
    args = parser.parse_args()
    main(args.count)
