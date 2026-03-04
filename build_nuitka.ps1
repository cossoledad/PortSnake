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

Write-Host "Done. Output directory: $OutputDir\PortSnake.dist"
