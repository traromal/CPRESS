#!/usr/bin/env bash
set -euo pipefail
BASE=$(dirname "$0")/..
cd "$BASE"

# Build wheel
python -m pip install --upgrade build
python -m build

# Build PyInstaller-based launcher for GUI
pip install pyinstaller
pyinstaller --onefile --name cpress-gui-gui gui.py

# Windows MSI (requires WiX toolset)
if command -v candle >/dev/null && command -v light >/dev/null; then
  cp dist/cpress-gui-gui.exe build/
  candle.exe -arch x64 installer/wxs/cpress.wxs
  light.exe -out installer/cpress.msi installer/cpress.wixobj
else
  echo "WiX not found; skipping MSI" >&2
fi

# macOS DMG
if [[ "$OSTYPE" == "darwin" ]]; then
  python -m pip install briefcase
  briefcase create macOS
  briefcase build macOS
  briefcase package macOS
  echo "DMG available under dist/" >&2
fi

# Linux AppImage stub
if command -v appimagetool >/dev/null; then
  mkdir -p AppDir/usr/bin
  cp dist/cpress-gui-gui AppDir/usr/bin/
  appimagetool AppDir cpress-gui.AppImage
else
  echo "appimagetool not found; skipping AppImage" >&2
fi
