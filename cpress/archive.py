from __future__ import annotations
"""
Core archive operations for cpress.

Formats:
  zip (AES optional; pyminizip fast path if installed)
  7z (py7zr optional)
  rar (read-only, rarfile optional)
  tar.{gz,bz2,xz,zst}, gz, zst
Features: progress callbacks, split volumes, policy-checked extraction, zstd presets/dicts, 7z solid tuning.
"""
import fnmatch
import gzip
import hashlib
import json
import shutil
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Tuple, Dict

try:
    import zstandard  # type: ignore
except Exception:  # pragma: no cover
    zstandard = None

try:
    import pyzipper  # type: ignore
except Exception:  # pragma: no cover
    pyzipper = None

try:
    import py7zr  # type: ignore
except Exception:  # pragma: no cover
    py7zr = None

try:
    import rarfile  # type: ignore
except Exception:  # pragma: no cover
    rarfile = None

try:
    import pyminizip  # type: ignore
except Exception:  # pragma: no cover
    pyminizip = None

FORMAT_ALIASES = {
    "zip": "zip",
    "7z": "7z",
    "rar": "rar",
    "tar.gz": "tar.gz",
    "tgz": "tar.gz",
    "tar.bz2": "tar.bz2",
    "tbz2": "tar.bz2",
    "tar.xz": "tar.xz",
    "txz": "tar.xz",
    "tar.zst": "tar.zst",
    "tzst": "tar.zst",
    "zst": "zst",
    "gz": "gz",
}

ProgressCb = Optional[Callable[[int, int, Path, Path], None]]  # processed, total, file, arcname

@dataclass
class Policy:
    allow_symlinks: bool = False
    max_path_len: int = 4096
    max_entry_bytes: Optional[int] = None

    @staticmethod
    def from_file(path: Optional[Path]) -> "Policy":
        if path is None or not path.exists():
            return Policy()
        data = json.loads(path.read_text(encoding="utf-8"))
        return Policy(
            allow_symlinks=bool(data.get("allow_symlinks", False)),
            max_path_len=int(data.get("max_path_len", 4096)),
            max_entry_bytes=data.get("max_entry_bytes"),
        )

@dataclass
class ArchiveEntry:
    name: str
    size: int
    compressed_size: Optional[int]

def detect_format(path: Path) -> Optional[str]:
    name = path.name.lower()
    for ext in (".7z", ".rar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".tar.zst", ".tzst", ".zip", ".zst", ".gz"):
        if name.endswith(ext):
            return FORMAT_ALIASES[ext.lstrip(".")]
    return None

def should_exclude(rel_path: Path, patterns: List[str]) -> bool:
    rel = rel_path.as_posix()
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel_path.name, pat):
            return True
    return False

def iter_files_with_arcname(target: Path, exclude: List[str]) -> Iterator[Tuple[Path, Path]]:
    target = target.resolve()
    base = target.parent
    if target.is_file():
        arc = target.relative_to(base)
        if not should_exclude(arc, exclude):
            yield target, arc
        return
    for path in target.rglob("*"):
        if path.is_file():
            arc = path.relative_to(base)
            if should_exclude(arc, exclude):
                continue
            yield path, arc

def total_size(inputs: List[Path], exclude: List[str]) -> int:
    return sum(fp.stat().st_size for t in inputs for fp, _ in iter_files_with_arcname(t, exclude))

def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest()

def build_manifest(inputs: List[Path], exclude: List[str]) -> dict:
    entries = {}
    for target in inputs:
        for file_path, arcname in iter_files_with_arcname(target, exclude):
            entries[arcname.as_posix()] = hash_file(file_path)
    return {"hash": "sha256", "entries": entries}

# splitting/joining

def split_file(path: Path, split_size: int) -> List[Path]:
    if split_size <= 0:
        return []
    parts: List[Path] = []
    with path.open("rb") as src:
        idx = 1
        while True:
            chunk = src.read(split_size)
            if not chunk:
                break
            part = path.with_name(f"{path.name}.part{idx:03d}")
            with part.open("wb") as dst:
                dst.write(chunk)
            parts.append(part)
            idx += 1
    return parts

def join_parts(first_part: Path) -> Path:
    stem = first_part.name.split(".part")[0]
    base = first_part.with_name(stem)
    parts = sorted(first_part.parent.glob(f"{stem}.part*"))
    with base.open("wb") as out:
        for p in parts:
            with p.open("rb") as src:
                shutil.copyfileobj(src, out)
    return base

# zstd presets
ZSTD_PRESETS: Dict[str, Dict[str, int]] = {
    "fast": {"level": 3},
    "balanced": {"level": 10},
    "ultra": {"level": 19},
    "lr": {"level": 15},
}

def _tick(cb: ProgressCb, processed: int, total: int, file_path: Path, arcname: Path):
    if cb:
        cb(processed, total, file_path, arcname)

# multithreaded zip via pyminizip fast path

def compress_zip_mt(inputs: List[Path], output: Path, level: Optional[int], exclude: List[str], password: Optional[str], progress_cb: ProgressCb, total_bytes: int) -> bool:
    if pyminizip is None:
        return False
    files = []
    arcs = []
    for target in inputs:
        for file_path, arcname in iter_files_with_arcname(target, exclude):
            files.append(str(file_path))
            parent = arcname.parent
            # pyminizip appends the filename to the provided arc name, so pass only the directory part.
            if parent == Path("."):
                arcs.append("")
            else:
                arcs.append(parent.as_posix())
    try:
        pyminizip.compress_multiple(files, arcs, str(output), password or "", level or 6)
        processed = 0
        for target in inputs:
            for file_path, arcname in iter_files_with_arcname(target, exclude):
                processed += file_path.stat().st_size
                _tick(progress_cb, processed, total_bytes, file_path, arcname)
        return True
    except Exception:
        return False


def compress_zip(inputs: List[Path], output: Path, level: Optional[int], exclude: List[str], password: Optional[str], zip_aes: bool, progress_cb: ProgressCb, total_bytes: int) -> None:
    if compress_zip_mt(inputs, output, level, exclude, password, progress_cb, total_bytes):
        return
    processed = 0
    if password:
        if pyzipper is None:
            raise ImportError("Encrypted zip requires optional dependency 'pyzipper' (install cpress[aes]).")
        compresslevel = 6 if level is None else level
        with pyzipper.AESZipFile(output, "w", compression=pyzipper.ZIP_LZMA, compresslevel=compresslevel) as zf:
            zf.setpassword(password.encode())
            zf.setencryption(pyzipper.WZ_AES if zip_aes else pyzipper.ZIP_CRYPTO)
            for target in inputs:
                for file_path, arcname in iter_files_with_arcname(target, exclude):
                    zf.write(file_path, arcname=arcname.as_posix())
                    processed += file_path.stat().st_size
                    _tick(progress_cb, processed, total_bytes, file_path, arcname)
    else:
        kwargs = {"compression": zipfile.ZIP_DEFLATED}
        if level is not None:
            kwargs["compresslevel"] = level
        with zipfile.ZipFile(output, "w", **kwargs) as zf:
            for target in inputs:
                for file_path, arcname in iter_files_with_arcname(target, exclude):
                    zf.write(file_path, arcname=arcname.as_posix())
                    processed += file_path.stat().st_size
                    _tick(progress_cb, processed, total_bytes, file_path, arcname)


def compress_7z(inputs: List[Path], output: Path, level: Optional[int], exclude: List[str], password: Optional[str], progress_cb: ProgressCb, total_bytes: int, solid: bool, threads: Optional[int], block_size: Optional[int] = None) -> None:
    if py7zr is None:
        raise ImportError("7z requires optional dependency 'py7zr' (install cpress[seven]).")
    filters = None
    if level is not None:
        filters = [{"id": py7zr.FILTER_LZMA2, "preset": level, "threads": threads or 0, "solid": solid}]
        if block_size:
            filters[0]["block"] = block_size
    processed = 0
    with py7zr.SevenZipFile(output, "w", password=password, filters=filters) as zf:
        for target in inputs:
            for file_path, arcname in iter_files_with_arcname(target, exclude):
                zf.write(file_path, arcname=arcname.as_posix())
                processed += file_path.stat().st_size
                _tick(progress_cb, processed, total_bytes, file_path, arcname)


def compress_tar(inputs: List[Path], output: Path, mode: str, level: Optional[int], exclude: List[str], progress_cb: ProgressCb, total_bytes: int) -> None:
    kwargs = {}
    if level is not None:
        kwargs["compresslevel"] = level
    processed = 0
    with tarfile.open(output, mode=mode, **kwargs) as tf:
        for target in inputs:
            for file_path, arcname in iter_files_with_arcname(target, exclude):
                tf.add(file_path, arcname=arcname.as_posix(), recursive=False)
                processed += file_path.stat().st_size
                _tick(progress_cb, processed, total_bytes, file_path, arcname)


def compress_tar_zst(inputs: List[Path], output: Path, level: Optional[int], threads: Optional[int], exclude: List[str], progress_cb: ProgressCb, total_bytes: int, dict_path: Optional[Path] = None, preset: Optional[str] = None) -> None:
    if zstandard is None:
        raise ImportError("tar.zst requires optional dependency 'zstandard' (install cpress[zstd]).")
    if preset and preset in ZSTD_PRESETS:
        level = ZSTD_PRESETS[preset].get("level", level)
    clevel = 3 if level is None else level
    dict_obj = None
    if dict_path:
        dict_obj = zstandard.ZstdCompressionDict(dict_path.read_bytes())
    processed = 0
    with output.open("wb") as fh:
        compressor = zstandard.ZstdCompressor(level=clevel, threads=threads or 0, dict_data=dict_obj)
        with compressor.stream_writer(fh) as zfh:
            with tarfile.open(fileobj=zfh, mode="w|") as tf:
                for target in inputs:
                    for file_path, arcname in iter_files_with_arcname(target, exclude):
                        tf.add(file_path, arcname=arcname.as_posix(), recursive=False)
                        processed += file_path.stat().st_size
                        _tick(progress_cb, processed, total_bytes, file_path, arcname)


def compress_gzip_single(input_file: Path, output: Path, level: Optional[int]) -> None:
    if not input_file.is_file():
        raise ValueError("gzip format only supports compressing a single file")
    compresslevel = 6 if level is None else level
    with input_file.open("rb") as src, gzip.open(output, "wb", compresslevel=compresslevel) as dst:
        shutil.copyfileobj(src, dst)


def compress_zst_single(input_file: Path, output: Path, level: Optional[int], threads: Optional[int], dict_path: Optional[Path] = None, preset: Optional[str] = None) -> None:
    if zstandard is None:
        raise ImportError("zst requires optional dependency 'zstandard' (install cpress[zstd]).")
    if not input_file.is_file():
        raise ValueError("zst format only supports compressing a single file")
    if preset and preset in ZSTD_PRESETS:
        level = ZSTD_PRESETS[preset].get("level", level)
    clevel = 3 if level is None else level
    dict_obj = None
    if dict_path:
        dict_obj = zstandard.ZstdCompressionDict(dict_path.read_bytes())
    with input_file.open("rb") as src, output.open("wb") as dst:
        compressor = zstandard.ZstdCompressor(level=clevel, threads=threads or 0, dict_data=dict_obj)
        with compressor.stream_writer(dst) as writer:
            shutil.copyfileobj(src, writer)


def compress(inputs: List[Path], output: Path, fmt: str, level: Optional[int], exclude: List[str], password: Optional[str], zip_aes: bool, progress_cb: ProgressCb = None, threads: Optional[int] = None, solid: bool = True, split_size: Optional[int] = None, zstd_dict: Optional[Path] = None, zstd_preset: Optional[str] = None, seven_block: Optional[int] = None) -> List[Path]:
    total_bytes = total_size(inputs, exclude)
    generated: List[Path] = []
    if fmt == "zip":
        compress_zip(inputs, output, level, exclude, password, zip_aes, progress_cb, total_bytes)
    elif fmt == "7z":
        compress_7z(inputs, output, level, exclude, password, progress_cb, total_bytes, solid=solid, threads=threads, block_size=seven_block)
    elif fmt == "tar.gz":
        compress_tar(inputs, output, "w:gz", level, exclude, progress_cb, total_bytes)
    elif fmt == "tar.bz2":
        compress_tar(inputs, output, "w:bz2", level, exclude, progress_cb, total_bytes)
    elif fmt == "tar.xz":
        compress_tar(inputs, output, "w:xz", level, exclude, progress_cb, total_bytes)
    elif fmt == "tar.zst":
        compress_tar_zst(inputs, output, level, threads, exclude, progress_cb, total_bytes, dict_path=zstd_dict, preset=zstd_preset)
    elif fmt == "gz":
        if len(inputs) != 1:
            raise ValueError("gzip compression requires exactly one input file")
        compress_gzip_single(inputs[0], output, level)
    elif fmt == "zst":
        if len(inputs) != 1:
            raise ValueError("zst compression requires exactly one input file")
        compress_zst_single(inputs[0], output, level, threads, dict_path=zstd_dict, preset=zstd_preset)
    else:
        raise ValueError(f"Unsupported format: {fmt}")
    generated.append(output)
    if split_size:
        generated.extend(split_file(output, split_size))
    return generated

# extraction helpers

def _safe_extract_member(tf: tarfile.TarFile, member: tarfile.TarInfo, dest: Path, policy: Policy) -> None:
    dest = dest.resolve()
    target = dest / member.name
    target_resolved = target.resolve()
    if dest not in target_resolved.parents and target_resolved != dest:
        raise ValueError(f"Blocked suspicious path in archive: {member.name}")
    if (member.issym() or member.islnk()) and not policy.allow_symlinks:
        raise ValueError(f"Blocked symlink/hardlink: {member.name}")
    if len(member.name) > policy.max_path_len:
        raise ValueError(f"Path too long: {member.name}")
    if policy.max_entry_bytes is not None and member.size > policy.max_entry_bytes:
        raise ValueError(f"Entry exceeds size limit: {member.name}")
    if member.isdir():
        target.mkdir(parents=True, exist_ok=True)
    elif member.isfile():
        target.parent.mkdir(parents=True, exist_ok=True)
        with tf.extractfile(member) as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)


def safe_tar_extract(tf: tarfile.TarFile, dest: Path, policy: Policy) -> None:
    for member in tf:
        _safe_extract_member(tf, member, dest, policy)


def decompress_zip(archive_path: Path, dest: Path, password: Optional[str]) -> None:
    with zipfile.ZipFile(archive_path, "r") as zf:
        if password:
            zf.setpassword(password.encode())
        zf.extractall(dest)


def decompress_7z(archive_path: Path, dest: Path, password: Optional[str]) -> None:
    if py7zr is None:
        raise ImportError("7z extraction requires optional dependency 'py7zr' (install cpress[seven]).")
    with py7zr.SevenZipFile(archive_path, "r", password=password) as zf:
        zf.extractall(path=dest)


def decompress_rar(archive_path: Path, dest: Path, password: Optional[str]) -> None:
    if rarfile is None:
        raise ImportError("rar extraction requires optional dependency 'rarfile' (install cpress[rar]).")
    with rarfile.RarFile(archive_path) as rf:
        if password:
            rf.setpassword(password)
        rf.extractall(dest)


def decompress_tar(archive_path: Path, dest: Path, mode: str, policy: Policy) -> None:
    with tarfile.open(archive_path, mode) as tf:
        safe_tar_extract(tf, dest, policy)


def decompress_tar_zst(archive_path: Path, dest: Path, policy: Policy) -> None:
    if zstandard is None:
        raise ImportError("tar.zst extraction requires optional dependency 'zstandard' (install cpress[zstd]).")
    with archive_path.open("rb") as fh:
        dctx = zstandard.ZstdDecompressor()
        with dctx.stream_reader(fh) as reader:
            with tarfile.open(fileobj=reader, mode="r|") as tf:
                safe_tar_extract(tf, dest, policy)


def decompress_gzip_single(archive_path: Path, dest: Path) -> Path:
    if dest.is_dir():
        dest_file = dest / archive_path.name[:-3]
    else:
        dest_file = dest
    with gzip.open(archive_path, "rb") as src, dest_file.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    return dest_file


def decompress_zst_single(archive_path: Path, dest: Path) -> Path:
    if zstandard is None:
        raise ImportError("zst extraction requires optional dependency 'zstandard' (install cpress[zstd]).")
    if dest.is_dir():
        dest_file = dest / archive_path.name[:-4]
    else:
        dest_file = dest
    with archive_path.open("rb") as fh, dest_file.open("wb") as dst:
        dctx = zstandard.ZstdDecompressor()
        with dctx.stream_reader(fh) as reader:
            shutil.copyfileobj(reader, dst)
    return dest_file


def decompress(archive_path: Path, dest: Path, fmt: str, password: Optional[str], policy: Optional[Policy] = None) -> None:
    policy = policy or Policy()
    dest.mkdir(parents=True, exist_ok=True) if dest.is_dir() or not dest.exists() else None
    if fmt == "zip":
        decompress_zip(archive_path, dest, password)
    elif fmt == "7z":
        decompress_7z(archive_path, dest, password)
    elif fmt == "rar":
        decompress_rar(archive_path, dest, password)
    elif fmt == "tar.gz":
        decompress_tar(archive_path, dest, "r:gz", policy)
    elif fmt == "tar.bz2":
        decompress_tar(archive_path, dest, "r:bz2", policy)
    elif fmt == "tar.xz":
        decompress_tar(archive_path, dest, "r:xz", policy)
    elif fmt == "tar.zst":
        decompress_tar_zst(archive_path, dest, policy)
    elif fmt == "gz":
        decompress_gzip_single(archive_path, dest)
    elif fmt == "zst":
        decompress_zst_single(archive_path, dest)
    else:
        raise ValueError(f"Unsupported format: {fmt}")

# listing / hashing / testing / summary

def list_archive(archive_path: Path, fmt: str, password: Optional[str]):
    entries: List[ArchiveEntry] = []
    if fmt == "zip":
        with zipfile.ZipFile(archive_path, "r") as zf:
            if password:
                zf.setpassword(password.encode())
            for info in zf.infolist():
                entries.append(ArchiveEntry(info.filename, info.file_size, info.compress_size))
    elif fmt == "7z":
        if py7zr is None:
            raise ImportError("7z listing requires optional dependency 'py7zr' (install cpress[seven]).")
        with py7zr.SevenZipFile(archive_path, "r", password=password) as zf:
            for info in zf.list():
                entries.append(ArchiveEntry(info.filename, info.uncompressed, info.compressed))
    elif fmt == "rar":
        if rarfile is None:
            raise ImportError("rar listing requires optional dependency 'rarfile' (install cpress[rar]).")
        with rarfile.RarFile(archive_path) as rf:
            if password:
                rf.setpassword(password)
            for info in rf.infolist():
                entries.append(ArchiveEntry(info.filename, info.file_size, info.compress_size))
    elif fmt in {"tar.gz", "tar.bz2", "tar.xz"}:
        mode = {"tar.gz": "r:gz", "tar.bz2": "r:bz2", "tar.xz": "r:xz"}[fmt]
        with tarfile.open(archive_path, mode) as tf:
            for member in tf.getmembers():
                if member.isfile():
                    entries.append(ArchiveEntry(member.name, member.size, None))
    elif fmt == "tar.zst":
        if zstandard is None:
            raise ImportError("tar.zst listing requires optional dependency 'zstandard' (install cpress[zstd]).")
        with archive_path.open("rb") as fh:
            dctx = zstandard.ZstdDecompressor()
            with dctx.stream_reader(fh) as reader:
                with tarfile.open(fileobj=reader, mode="r|") as tf:
                    for member in tf:
                        if member.isfile():
                            entries.append(ArchiveEntry(member.name, member.size, None))
    elif fmt == "gz":
        entries.append(ArchiveEntry(archive_path.name[:-3], archive_path.stat().st_size, archive_path.stat().st_size))
    elif fmt == "zst":
        entries.append(ArchiveEntry(archive_path.name[:-4], _measure_zst_size(archive_path), archive_path.stat().st_size))
    else:
        raise ValueError(f"Unsupported format: {fmt}")
    return entries


def _hash_stream(stream, chunk=1024 * 256):
    h = hashlib.sha256()
    for chunk_bytes in iter(lambda: stream.read(chunk), b""):
        h.update(chunk_bytes)
    return h.hexdigest()


def hash_archive(archive_path: Path, fmt: str, password: Optional[str]) -> dict:
    entries = {}
    if fmt == "zip":
        with zipfile.ZipFile(archive_path, "r") as zf:
            if password:
                zf.setpassword(password.encode())
            for info in zf.infolist():
                with zf.open(info, "r") as f:
                    entries[info.filename] = _hash_stream(f)
    elif fmt == "7z":
        if py7zr is None:
            raise ImportError("7z hashing requires optional dependency 'py7zr' (install cpress[seven]).")
        with py7zr.SevenZipFile(archive_path, "r", password=password) as zf:
            for name in zf.getnames():
                data = zf.read([name])[name]
                entries[name] = hashlib.sha256(data).hexdigest()
    elif fmt == "rar":
        if rarfile is None:
            raise ImportError("rar hashing requires optional dependency 'rarfile' (install cpress[rar]).")
        with rarfile.RarFile(archive_path) as rf:
            if password:
                rf.setpassword(password)
            for info in rf.infolist():
                with rf.open(info) as f:
                    entries[info.filename] = _hash_stream(f)
    elif fmt in {"tar.gz", "tar.bz2", "tar.xz"}:
        mode = {"tar.gz": "r:gz", "tar.bz2": "r:bz2", "tar.xz": "r:xz"}[fmt]
        with tarfile.open(archive_path, mode) as tf:
            for member in tf.getmembers():
                if member.isfile():
                    with tf.extractfile(member) as f:
                        entries[member.name] = _hash_stream(f)
    elif fmt == "tar.zst":
        if zstandard is None:
            raise ImportError("tar.zst hashing requires optional dependency 'zstandard' (install cpress[zstd]).")
        with archive_path.open("rb") as fh:
            dctx = zstandard.ZstdDecompressor()
            with dctx.stream_reader(fh) as reader:
                with tarfile.open(fileobj=reader, mode="r|") as tf:
                    for member in tf:
                        if member.isfile():
                            with tf.extractfile(member) as f:
                                entries[member.name] = _hash_stream(f)
    elif fmt == "gz":
        with gzip.open(archive_path, "rb") as f:
            entries[archive_path.name[:-3]] = _hash_stream(f)
    elif fmt == "zst":
        if zstandard is None:
            raise ImportError("zst hashing requires optional dependency 'zstandard' (install cpress[zstd]).")
        with archive_path.open("rb") as fh:
            dctx = zstandard.ZstdDecompressor()
            with dctx.stream_reader(fh) as reader:
                entries[archive_path.name[:-4]] = _hash_stream(reader)
    else:
        raise ValueError(f"Unsupported format: {fmt}")
    return {"hash": "sha256", "entries": entries}


def _measure_zst_size(path: Path) -> int:
    if zstandard is None:
        raise ImportError("zstandard required (install cpress[zstd])")
    total = 0
    with path.open("rb") as fh:
        dctx = zstandard.ZstdDecompressor()
        with dctx.stream_reader(fh) as reader:
            for chunk in iter(lambda: reader.read(1024 * 256), b""):
                total += len(chunk)
    return total


def test_archive(archive_path: Path, fmt: str, password: Optional[str]) -> None:
    if fmt == "zip":
        with zipfile.ZipFile(archive_path, "r") as zf:
            if password:
                zf.setpassword(password.encode())
            bad = zf.testzip()
            if bad:
                raise ValueError(f"Corrupted member: {bad}")
    elif fmt == "7z":
        if py7zr is None:
            raise ImportError("7z test requires optional dependency 'py7zr' (install cpress[seven]).")
        with py7zr.SevenZipFile(archive_path, "r", password=password) as zf:
            zf.test()
    elif fmt == "rar":
        if rarfile is None:
            raise ImportError("rar test requires optional dependency 'rarfile' (install cpress[rar]).")
        with rarfile.RarFile(archive_path) as rf:
            if password:
                rf.setpassword(password)
            for info in rf.infolist():
                with rf.open(info) as f:
                    for _ in iter(lambda: f.read(1024 * 256), b""):
                        pass
    elif fmt in {"tar.gz", "tar.bz2", "tar.xz"}:
        mode = {"tar.gz": "r:gz", "tar.bz2": "r:bz2", "tar.xz": "r:xz"}[fmt]
        with tarfile.open(archive_path, mode) as tf:
            for member in tf.getmembers():
                if member.isfile():
                    extracted = tf.extractfile(member)
                    if extracted:
                        while extracted.read(1024 * 256):
                            pass
    elif fmt == "tar.zst":
        if zstandard is None:
            raise ImportError("tar.zst test requires optional dependency 'zstandard' (install cpress[zstd]).")
        with archive_path.open("rb") as fh:
            dctx = zstandard.ZstdDecompressor()
            with dctx.stream_reader(fh) as reader:
                with tarfile.open(fileobj=reader, mode="r|") as tf:
                    for member in tf:
                        if member.isfile():
                            extracted = tf.extractfile(member)
                            if extracted:
                                while extracted.read(1024 * 256):
                                    pass
    elif fmt == "gz":
        with gzip.open(archive_path, "rb") as src:
            while src.read(1024 * 256):
                pass
    elif fmt == "zst":
        if zstandard is None:
            raise ImportError("zst test requires optional dependency 'zstandard' (install cpress[zstd]).")
        _measure_zst_size(archive_path)
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def summarize(archive_path: Path, fmt: str, password: Optional[str]) -> dict:
    entries = list_archive(archive_path, fmt, password)
    total_uncompressed = sum(e.size for e in entries)
    compressed_size = archive_path.stat().st_size
    ratio = (1 - compressed_size / total_uncompressed) if total_uncompressed else 0
    return {
        "path": str(archive_path),
        "format": fmt,
        "entries": len(entries),
        "uncompressed_bytes": total_uncompressed,
        "archive_bytes": compressed_size,
        "ratio": ratio,
    }
