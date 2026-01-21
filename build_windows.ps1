<#
Build script for Windows: creates a venv, installs requirements and builds a single .exe using PyInstaller.
Usage: Open PowerShell in repo root and run:
    .\build_windows.ps1
#>

param(
    [string]$Entry = "src\decentralis-client\main.py",
    [string]$OutDir = "dist",
    [string]$Name = "decentralis-client"
)

Write-Host "Creating virtualenv .venv..."
python -m venv .venv

Write-Host "Activating virtualenv and installing requirements..."
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Write-Host "Cleaning PyInstaller cache..."
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
if (Test-Path "$Name.spec") { Remove-Item -Force "$Name.spec" }

Write-Host "Running PyInstaller..."
pyinstaller --onefile --name $Name --icon .\assets\icon.ico --distpath $OutDir $Entry

if ($LASTEXITCODE -eq 0) {
    Write-Host "Build réussi. Fichier généré dans: $OutDir\$Name.exe"
} else {
    Write-Host "Build échoué (PyInstaller retourné $LASTEXITCODE)"
}
