from __future__ import annotations
"""
Command-line interface for cpress.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import archive
from . import parity as parity_mod

CONFIG_PATH = Path(os.path.expanduser("~/.cpress/config.json"))
SUPPORTED_FORMATS = sorted(set(archive.FORMAT_ALIASES.values()))
COMPRESSIBLE = [f for f in SUPPORTED_FORMATS if f != "rar"]


def load_config() -> Dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def apply_profile(args: argparse.Namespace, cfg: Dict) -> argparse.Namespace:
    profile_name = getattr(args, "profile", None)
    if not profile_name:
        return args
    prof = cfg.get("profiles", {}).get(profile_name, {})
    # only fill missing options
    for key, val in prof.items():
        if getattr(args, key, None) in (None, False, [], 0):
            setattr(args, key, val)
    return args


def human_bytes(num: float) -> str:
    step = 1024.0
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(num)
    for unit in units:
        if value < step:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= step
    return f"{value:.1f} PiB"


def parse_size(text: Optional[str]) -> Optional[int]:
    if text is None:
        return None
    multipliers = {"k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}
    txt = text.strip().lower()
    if txt[-1] in multipliers:
        return int(float(txt[:-1]) * multipliers[txt[-1]])
    return int(txt)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cpress",
        description="High-level archiver (zip, 7z, tar.gz/bz2/xz/zst, gz, rar read) with AES, presets, policy, manifests",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    sub = parser.add_subparsers(dest="command", required=True)

    comp = sub.add_parser("compress", help="Create an archive")
    comp.add_argument("inputs", nargs="+", type=Path)
    comp.add_argument("-o", "--output", type=Path, required=True)
    comp.add_argument("-f", "--format", choices=COMPRESSIBLE)
    comp.add_argument("-l", "--level", type=int, choices=range(0, 23), metavar="[0-22]")
    comp.add_argument("-x", "--exclude", action="append", default=[])
    comp.add_argument("--overwrite", action="store_true")
    comp.add_argument("-p", "--password", help="Password for zip/7z")
    comp.add_argument("--password-env", help="Env var containing password")
    comp.add_argument("--zip-aes", dest="zip_aes", action="store_true", default=True)
    comp.add_argument("--no-zip-aes", dest="zip_aes", action="store_false")
    comp.add_argument("--manifest", type=Path)
    comp.add_argument("--parity", action="store_true", help="Write archive parity JSON")
    comp.add_argument("--progress", action="store_true")
    comp.add_argument("--threads", type=int, default=0)
    comp.add_argument("--solid", dest="solid", action="store_true", default=True)
    comp.add_argument("--no-solid", dest="solid", action="store_false")
    comp.add_argument("--split-size", type=str, help="e.g. 100M or 1G")
    comp.add_argument("--zstd-dict", type=Path)
    comp.add_argument("--zstd-preset", choices=list(archive.ZSTD_PRESETS.keys()))
    comp.add_argument("--7z-block", dest="seven_block", type=int)
    comp.add_argument("--policy", type=Path, help="JSON policy for extraction safety (used on extract)")
    comp.add_argument("--verify", dest="verify", action="store_true", default=True)
    comp.add_argument("--no-verify", dest="verify", action="store_false")
    comp.add_argument("--stats", action="store_true")
    comp.add_argument("--profile", help="Profile name from ~/.cpress/config.json")
    comp.add_argument("--events-json", action="store_true", help="Emit JSON events to stdout")

    decomp = sub.add_parser("extract", help="Extract an archive")
    decomp.add_argument("archive", type=Path)
    decomp.add_argument("-d", "--dest", type=Path, default=Path("."))
    decomp.add_argument("-f", "--format", choices=SUPPORTED_FORMATS)
    decomp.add_argument("-p", "--password")
    decomp.add_argument("--password-env", help="Env var containing password")
    decomp.add_argument("--policy", type=Path, help="JSON policy for extraction safety")

    ls = sub.add_parser("list", help="List contents")
    ls.add_argument("archive", type=Path)
    ls.add_argument("-f", "--format", choices=SUPPORTED_FORMATS)
    ls.add_argument("-p", "--password")
    ls.add_argument("--password-env", help="Env var containing password")

    info = sub.add_parser("info", help="Show summary")
    info.add_argument("archive", type=Path)
    info.add_argument("-f", "--format", choices=SUPPORTED_FORMATS)
    info.add_argument("-p", "--password")
    info.add_argument("--password-env", help="Env var containing password")

    tst = sub.add_parser("test", help="Validate archive")
    tst.add_argument("archive", type=Path)
    tst.add_argument("-f", "--format", choices=SUPPORTED_FORMATS)
    tst.add_argument("-p", "--password")
    tst.add_argument("--password-env", help="Env var containing password")

    verify = sub.add_parser("verify", help="Verify archive against manifest")
    verify.add_argument("archive", type=Path)
    verify.add_argument("-m", "--manifest", type=Path, required=True)
    verify.add_argument("-f", "--format", choices=SUPPORTED_FORMATS)
    verify.add_argument("-p", "--password")
    verify.add_argument("--password-env", help="Env var containing password")

    repair = sub.add_parser("repair", help="Repair archive via parity + checkpoint")
    repair.add_argument("parity_file", type=Path)
    repair.add_argument("-o", "--output", type=Path, help="Destination for repaired archive")
    parity = sub.add_parser("parity-verify", help="Verify parity file")
    parity.add_argument("parity_file", type=Path)

    sub.add_parser("formats", help="List supported formats")
    return parser.parse_args(argv)


def ensure_overwrite(path: Path, allow: bool) -> None:
    if path.exists() and not allow:
        raise FileExistsError(f"{path} already exists (use --overwrite)")
    if path.exists() and allow:
        if path.is_dir():
            import shutil
            shutil.rmtree(path)
        else:
            path.unlink()


def resolve_format(path: Path, explicit: Optional[str]) -> str:
    fmt = explicit or archive.detect_format(path)
    if fmt is None:
        raise ValueError("Could not infer format; pass --format")
    return fmt


def progress_tqdm(total_bytes: int):
    try:
        from tqdm import tqdm
    except Exception:
        def fallback(processed: int, total: int, file_path: Path, arcname: Path) -> None:
            pct = (processed / total * 100) if total else 0
            print(f"[{pct:6.2f}%] {arcname.as_posix()}")
        return fallback, None
    bar = tqdm(total=total_bytes, unit="B", unit_scale=True, unit_divisor=1024)
    def _cb(processed: int, total: int, file_path: Path, arcname: Path) -> None:
        bar.n = processed
        bar.set_postfix(file=arcname.as_posix())
        bar.refresh()
    return _cb, bar


def get_password(args: argparse.Namespace) -> Optional[str]:
    if args.password:
        if len(args.password) < 8:
            print("Warning: password length < 8", file=sys.stderr)
        return args.password
    if args.password_env:
        val = os.environ.get(args.password_env)
        if val:
            if len(val) < 8:
                print("Warning: password length < 8", file=sys.stderr)
            return val
    return None


def emit_event(enabled: bool, payload: dict):
    if enabled:
        print(json.dumps(payload))


def cmd_compress(args: argparse.Namespace) -> None:
    cfg = load_config()
    args = apply_profile(args, cfg)
    fmt = resolve_format(args.output, args.format)
    ensure_overwrite(args.output, args.overwrite)
    inputs = [p.expanduser() for p in args.inputs]
    manifest_data = archive.build_manifest(inputs, args.exclude) if args.manifest else None
    progress_cb = None
    closer = None
    if args.progress:
        total_bytes = archive.total_size(inputs, args.exclude)
        progress_cb, closer = progress_tqdm(total_bytes)
    split_bytes = parse_size(args.split_size)
    password = get_password(args)
    start = time.time()
    outputs = archive.compress(
        inputs,
        args.output,
        fmt,
        args.level,
        args.exclude,
        password,
        args.zip_aes,
        progress_cb=progress_cb,
        threads=args.threads or None,
        solid=args.solid,
        split_size=split_bytes,
        zstd_dict=args.zstd_dict,
        zstd_preset=args.zstd_preset,
        seven_block=args.seven_block,
    )
    if closer:
        closer.close()
    if args.verify:
        archive.test_archive(args.output, fmt, password)
        emit_event(args.events_json, {"event": "post_test", "status": "ok", "archive": str(args.output)})
        print("Post-write test: OK")
    elapsed = time.time() - start
    print(f"Created {args.output} ({fmt})")
    if split_bytes:
        print(f"Split into {len(outputs)-1} parts of ~{args.split_size} each")
    if args.manifest and manifest_data:
        manifest = {
            "format": fmt,
            "hash": manifest_data["hash"],
            "entries": manifest_data["entries"],
            "source": {"inputs": [p.as_posix() for p in inputs], "archive": args.output.as_posix()},
        }
        args.manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"Wrote manifest -> {args.manifest}")
    if args.parity:
        parity_path = parity_mod.write_parity(args.output)
        print(f"Wrote parity -> {parity_path}")
    if args.stats:
        sz = args.output.stat().st_size
        total = archive.total_size(inputs, args.exclude)
        ratio = (1 - sz / total) * 100 if total else 0
        rate = sz / elapsed if elapsed > 0 else 0
        stats = {"time_s": elapsed, "size": sz, "input": total, "ratio_pct": ratio, "throughput": rate}
        print(f"Stats: time={elapsed:.2f}s, size={human_bytes(sz)}, input={human_bytes(total)}, ratio={ratio:.2f}%, throughput={human_bytes(rate)}/s")
        emit_event(args.events_json, {"event": "stats", **stats})


def _auto_join(archive_path: Path) -> Path:
    if archive_path.exists():
        return archive_path
    candidate = archive_path.with_suffix(archive_path.suffix + ".part001")
    if candidate.exists():
        print(f"Joining parts starting at {candidate}...")
        return archive.join_parts(candidate)
    return archive_path


def cmd_extract(args: argparse.Namespace) -> None:
    target = _auto_join(args.archive)
    fmt = resolve_format(target, args.format)
    policy = archive.Policy.from_file(args.policy)
    password = get_password(args)
    archive.decompress(target, args.dest, fmt, password, policy=policy)
    print(f"Extracted to {args.dest}")


def cmd_list(args: argparse.Namespace) -> None:
    target = _auto_join(args.archive)
    fmt = resolve_format(target, args.format)
    password = get_password(args)
    entries = archive.list_archive(target, fmt, password)
    for e in entries:
        size = human_bytes(e.size)
        comp = f" [{human_bytes(e.compressed)}]" if e.compressed is not None else ""
        print(f"{e.name} ({size}{comp})")


def cmd_info(args: argparse.Namespace) -> None:
    target = _auto_join(args.archive)
    fmt = resolve_format(target, args.format)
    password = get_password(args)
    summary = archive.summarize(target, fmt, password)
    summary["archive_h"] = human_bytes(summary["archive_bytes"])
    summary["uncompressed_h"] = human_bytes(summary["uncompressed_bytes"])
    summary["ratio_percent"] = round(summary["ratio"] * 100, 2)
    print(json.dumps(summary, indent=2))


def cmd_test(args: argparse.Namespace) -> None:
    target = _auto_join(args.archive)
    fmt = resolve_format(target, args.format)
    password = get_password(args)
    archive.test_archive(target, fmt, password)
    print("OK")


def cmd_verify(args: argparse.Namespace) -> None:
    target = _auto_join(args.archive)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    fmt = args.format or manifest.get("format") or resolve_format(target, None)
    password = get_password(args)
    live = archive.hash_archive(target, fmt, password)
    expected_entries = manifest.get("entries", {})
    live_entries = live.get("entries", {})

    missing = sorted(set(expected_entries) - set(live_entries))
    extra = sorted(set(live_entries) - set(expected_entries))
    mismatched = [name for name in expected_entries if name in live_entries and expected_entries[name] != live_entries[name]]

    if missing or extra or mismatched:
        msg_parts = []
        if missing:
            msg_parts.append(f"missing: {missing}")
        if extra:
            msg_parts.append(f"unexpected: {extra}")
        if mismatched:
            msg_parts.append(f"hash mismatch: {mismatched}")
        raise ValueError("; ".join(msg_parts))

    print("Verify OK")


def cmd_parity_verify(args: argparse.Namespace) -> None:
    parity_mod.verify_parity(args.parity_file)
    print("Parity OK")


def cmd_repair(args: argparse.Namespace) -> None:
    repaired = parity_mod.repair_from_parity(args.parity_file, args.output)
    print(f"Repaired archive -> {repaired}")


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "compress":
            cmd_compress(args)
        elif args.command == "extract":
            cmd_extract(args)
        elif args.command == "list":
            cmd_list(args)
        elif args.command == "info":
            cmd_info(args)
        elif args.command == "test":
            cmd_test(args)
        elif args.command == "verify":
            cmd_verify(args)
        elif args.command == "parity-verify":
            cmd_parity_verify(args)
        elif args.command == "repair":
            cmd_repair(args)
        elif args.command == "formats":
            print("Supported formats:")
            for fmt in SUPPORTED_FORMATS:
                print(f"  - {fmt}")
        else:
            raise ValueError(f"Unknown command {args.command}")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
