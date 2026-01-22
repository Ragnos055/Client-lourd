#!/usr/bin/env bash
# Build script for macOS: creates a venv, installs requirements and builds a .app bundle with PyInstaller.
# Usage: run from repo root: `./build_macos.sh`

set -euo pipefail

ENTRY="src/decentralis-client/main.py"
OUTDIR="dist"
NAME="decentralis-client"

echo "Creating virtualenv .venv..."
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "Running PyInstaller to create macOS app bundle..."

# Check if icon exists
ICON_OPT=""
if [ -f "assets/icon.icns" ]; then
    ICON_OPT="--icon=assets/icon.icns"
    echo "Using icon: assets/icon.icns"
elif [ -f "assets/icon.png" ]; then
    echo "Note: For best results on macOS, provide an .icns file (assets/icon.icns)"
    echo "Using PNG icon as fallback..."
    ICON_OPT="--icon=assets/icon.png"
fi

# Build the app bundle
pyinstaller --onefile --windowed --name "${NAME}" ${ICON_OPT} "${ENTRY}"

if [ $? -eq 0 ]; then
    echo ""
    echo "Build réussi!"
    echo "Exécutable: ${OUTDIR}/${NAME}"
    echo "App bundle: ${OUTDIR}/${NAME}.app"
    echo ""
    echo "Pour créer un DMG (optionnel), vous pouvez utiliser:"
    echo "  hdiutil create -volname '${NAME}' -srcfolder ${OUTDIR}/${NAME}.app -ov -format UDZO ${OUTDIR}/${NAME}.dmg"
else
    echo "Build échoué (PyInstaller retourné $?)"
    exit 1
fi
