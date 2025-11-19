#!/usr/bin/env bash
# Build script for Linux: creates a venv, installs requirements and builds a single ELF executable with PyInstaller,
# then packages it into an AppImage using appimagetool.
# Usage: run from repo root: `./build_linux.sh`

set -euo pipefail

ENTRY="src/decentralis-client/main.py"
OUTDIR="dist"
NAME="decentralis-client"

echo "Creating virtualenv .venv..."
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "Running PyInstaller to create single-file executable..."
pyinstaller --onefile --name "${NAME}" "${ENTRY}"

mkdir -p ${OUTDIR}
cp dist/${NAME} ${OUTDIR}/

APPDIR="${NAME}.AppDir"
echo "Preparing AppDir (${APPDIR})..."
rm -rf ${APPDIR}
mkdir -p ${APPDIR}/usr/bin
mkdir -p ${APPDIR}/usr/share/applications
mkdir -p ${APPDIR}/usr/share/icons/hicolor/256x256/apps

cp assets/icon.png ${APPDIR}/usr/share/icons/hicolor/256x256/apps/${NAME}.png
cp ${OUTDIR}/${NAME} ${APPDIR}/usr/bin/${NAME}

# Create a .desktop entry
cat > ${APPDIR}/usr/share/applications/${NAME}.desktop <<EOF
[Desktop Entry]
Name=Decentralis Client
Exec=${NAME}
Type=Application
Categories=Network;
Terminal=false
EOF

echo "Note: No icon provided. If you have an icon, place it in ${APPDIR}/usr/share/icons/hicolor/256x256/apps/${NAME}.png"

# Download appimagetool if not present
if ! command -v appimagetool &> /dev/null; then
  echo "appimagetool not found. Attempting to download appimagetool (x86_64)..."
  TMP_TOOL="appimagetool-x86_64.AppImage"
  if [ ! -f "$TMP_TOOL" ]; then
    wget -O $TMP_TOOL "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x $TMP_TOOL
  fi
  APPIMAGETOOL="./$TMP_TOOL"
else
  APPIMAGETOOL="appimagetool"
fi

echo "Creating AppImage..."
$APPIMAGETOOL ${APPDIR} ${OUTDIR}/${NAME}.AppImage

echo "Done. Outputs in ${OUTDIR}/"
