# Build BGUTube standalone exe.
# Run from project root: .\build.ps1

Set-Location $PSScriptRoot

Write-Host "Cleaning previous build..." -ForegroundColor Cyan
if (Test-Path dist)  { Remove-Item -Recurse -Force dist }
if (Test-Path build) { Remove-Item -Recurse -Force build }

Write-Host "Running PyInstaller..." -ForegroundColor Cyan
pyinstaller BGUTube.spec

if ($LASTEXITCODE -eq 0) {
    $size = [math]::Round((Get-Item dist\BGUTube.exe).Length / 1MB, 1)
    Write-Host "Build successful!  dist\BGUTube.exe  ($size MB)" -ForegroundColor Green
} else {
    Write-Host "Build FAILED. Check output above." -ForegroundColor Red
    exit 1
}
