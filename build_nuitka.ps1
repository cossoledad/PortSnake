param(
    [string]$PythonExe = "python",
    [string]$OutputDir = "dist"
)

$ErrorActionPreference = "Stop"

Write-Host "Building PortSnake with Nuitka..."

& $PythonExe -m nuitka `
  --standalone `
  --assume-yes-for-downloads `
  --windows-console-mode=disable `
  --windows-uac-admin `
  --enable-plugin=tk-inter `
  --output-dir="$OutputDir" `
  --output-filename="PortSnake" `
  app.py

if ($LASTEXITCODE -ne 0) {
    throw "Nuitka build failed with exit code $LASTEXITCODE"
}

$targetDist = Join-Path $OutputDir "PortSnake.dist"
$distDirs = Get-ChildItem -Path $OutputDir -Directory -Filter "*.dist" | Sort-Object LastWriteTime -Descending
if ($distDirs.Count -eq 0) {
    throw "Nuitka build finished but no *.dist directory found in '$OutputDir'"
}

$actualDist = $distDirs[0].FullName
if ($actualDist -ne $targetDist) {
    if (Test-Path $targetDist) {
        Remove-Item -Recurse -Force $targetDist
    }
    Move-Item -Path $actualDist -Destination $targetDist
}

Write-Host "Done. Output directory: $targetDist"
