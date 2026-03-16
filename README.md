# cpress

A high-level, safe archiver. Supports `zip`, `7z` (py7zr), read-only `rar` (rarfile), `tar.gz`, `tar.bz2`, `tar.xz`, `tar.zst`, single-file `gz`, and `zst`. Optional extras add AES zip, zstd presets/dicts, fast zip (pyminizip), progress bars (tqdm), and 7z.

## Install
- Core: `python -m pip install .`
- With extras: `python -m pip install .[all]`
- Dev/editable: `python -m pip install -e .`
- Isolated: `pipx install .[all]`

## CLI
```
cpress compress <paths...> -o out.zip [--format zip|7z|tar.gz|tar.bz2|tar.xz|tar.zst|gz|zst]
                         [--level 0-22] [--threads N] [-x pattern] [--overwrite]
                         [--password pwd] [--no-zip-aes] [--manifest manifest.json]
                         [--progress] [--solid/--no-solid] [--split-size 100M]
                         [--zstd-dict dict] [--zstd-preset fast|balanced|ultra|lr]
                         [--7z-block N] [--no-verify] [--stats]

cpress extract archive.zip -d dest [--password pwd] [--policy policy.json]
# auto-joins .partNNN if present

cpress list|info|test|verify ...
```

## Safety & integrity
- Policy file for extraction (`allow_symlinks`, `max_path_len`, `max_entry_bytes`).
- `--manifest` writes SHA-256 per file; `verify` hashes archive contents without extracting.
- `--verify` (default) tests archive after write.
- Split volumes (`--split-size`) + auto-join on extract.

## Performance
- zstd presets/dicts; threaded zstd. Optional fast zip via pyminizip. 7z solid/block tuning. Progress bars with tqdm when installed; `--stats` prints time/throughput.

## GUI & Shell
- Minimal Tk GUI: `python gui.py`
- Windows context menu installer: `powershell -ExecutionPolicy Bypass -File scripts/install_context_menu.ps1` (run elevated).

## Installers
- Build scripts for MSI/DMG/AppImage + PyInstaller GUI live in `scripts/`. Run `scripts/build_installers.sh` after installing the required toolchains (`WiX`, `briefcase`, `appimagetool`, `pyinstaller`). Sign the outputs with your certificates for QA trust.

## Bench & CI
- Bench: `python scripts/bench.py <input_dir>` (compares to 7z CLI if available).
- CI workflow at `.github/workflows/ci.yml` (installs extras, pytest, bench dry-run plus nightly benchmarks and fuzz runs).

## Build
```
python -m pip install build
python -m build
```

Roadmap placeholders: richer progress/ETA, parity/recovery, signed installers, full GUI polish, reproducible builds.
- Run `--parity` / `parity-verify` / `repair` commands as part of your release pipeline to prove recoverability.
