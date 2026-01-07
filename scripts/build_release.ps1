$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
$ReleaseDir = "$ProjectRoot\release"
$AkariFlutterDir = "$ProjectRoot\akari_flutter"
$ScriptsDir = "$ProjectRoot\scripts"

Write-Host "Cleaning release directory..."
if (Test-Path $ReleaseDir) {
    Remove-Item -Recurse -Force $ReleaseDir
}
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

# 1. Build Flutter App
Write-Host "Building Flutter Windows application..."
Push-Location $AkariFlutterDir
flutter build windows --release
if ($LASTEXITCODE -ne 0) {
    Write-Error "Flutter build failed!"
}
Pop-Location

# Copy Flutter artifacts
Write-Host "Copying Flutter artifacts..."
$FlutterBuildDir = "$AkariFlutterDir\build\windows\x64\runner\Release"
Copy-Item -Recurse -Force "$FlutterBuildDir\*" $ReleaseDir

# 2. Build Python Backend
Write-Host "Building Python backend..."
# Ensure pyinstaller is installed
# pip install pyinstaller

# Create dist directory for python build
$PythonDist = "$ProjectRoot\build\python_dist"
if (Test-Path $PythonDist) {
    Remove-Item -Recurse -Force $PythonDist
}

# Run PyInstaller
# Using --onedir for faster startup, or --onefile for single exe. 
# --onedir is often safer for complex dependencies. Let's try --onedir first to avoid unpacking issues, 
# but considering the user might want a clean folder, let's put it in a subdirectory 'backend' or similar.
# For simplicity in this 'first release', let's try to output a single executable if possible, 
# but given it has Rust dependencies, directory mode is safer.
# Adjusting to output 'akari_backend.exe'

pyinstaller --noconfirm --clean --distpath "$ReleaseDir\backend" --workpath "$ProjectRoot\build\python_build" --name "akari_backend" --onedir --contents-directory "." "$ScriptsDir\run_async_remote_proxy.py"

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller build failed!"
}

# Copy config or other necessary files if any
# (Currently assuming no external config files needed for basic run, or they are embedded)

Write-Host "Build complete!"
Write-Host "Release artifacts are in: $ReleaseDir"
