# Build instructions

This file explains how to build a Windows `.exe` and a Linux `AppImage` for the Decentralis client.

Prerequisites
- Python 3.8+ installed.
- On Windows: PowerShell and the ability to run scripts (ExecutionPolicy may need adjustment).
- On Linux: `wget`, and ability to run shell scripts. `appimagetool` will be downloaded automatically by the script if missing.

Windows (.exe)
1. Open PowerShell in the repository root.
2. Run:
```
.\build_windows.ps1
```
3. Output `.exe` placed in `dist\decentralis-client.exe`.

Linux (AppImage)
1. Make the script executable and run it from the repo root:
```
chmod +x build_linux.sh
./build_linux.sh
```
2. The resulting AppImage will be in `dist/decentralis-client.AppImage`.

Notes
- The build scripts create a local virtualenv `.venv` and install `pyinstaller`.
- `tkinter` is part of the Python standard library on most systems; if it is missing, install your system package (for Debian/Ubuntu: `sudo apt install python3-tk`).
- The AppImage script creates a minimal AppDir and attempts to download `appimagetool` if it's not already available.

If you want, I can:
- Add an icon into `assets/` and use it for the AppImage and Windows build.
- Create CI workflows (GitHub Actions) to produce artifacts automatically.
