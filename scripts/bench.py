#!/usr/bin/env python3
"""
Lightweight benchmark harness comparing cpress vs external 7z/zstd if available.
Usage: python scripts/bench.py <input_dir>
"""
from __future__ import annotations
import shutil
import subprocess
import sys
import time
from pathlib import Path

from cpress import archive


def run_cmd(cmd):
    start = time.time()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return proc.returncode, time.time() - start, proc.stdout, proc.stderr


def bench_cpress(src: Path, out: Path):
    start = time.time()
    archive.compress([src], out, "tar.zst", level=10, exclude=[], password=None, zip_aes=True, threads=0)
    elapsed = time.time() - start
    size = out.stat().st_size
    return elapsed, size


def bench_external(src: Path, out: Path):
    if shutil.which("7z"):
        return run_cmd(["7z", "a", "-t7z", "-m0=LZMA2", "-mx=9", str(out), str(src)])
    return None


def main():
    if len(sys.argv) < 2:
        print("Usage: bench.py <input_dir>")
        sys.exit(1)
    src = Path(sys.argv[1]).resolve()
    out_cpress = Path("bench_cpress.tar.zst")
    out_ext = Path("bench_7z.7z")

    c_time, c_size = bench_cpress(src, out_cpress)
    print(f"cpress tar.zst: {c_time:.2f}s, {c_size/1024/1024:.1f} MiB")

    ext = bench_external(src, out_ext)
    if ext:
        code, elapsed, _, _ = ext
        size = out_ext.stat().st_size if out_ext.exists() else 0
        print(f"7z mx=9: {elapsed:.2f}s, {size/1024/1024:.1f} MiB (rc={code})")
    else:
        print("7z CLI not found; skipping external bench")


if __name__ == "__main__":
    main()
