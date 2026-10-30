$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($env:OS -ne 'Windows_NT') { throw 'Run on Windows x64 with Python 3.12.' }
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
$release = Join-Path $PSScriptRoot "releases\$stamp"
New-Item -ItemType Directory -Path $release | Out-Null
# Each build is isolated. Never overwrite an installed app or previous release.
py -3.12 -m venv (Join-Path $release 'venv')
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 x64 is required.' }
$python = Join-Path $release 'venv\Scripts\python.exe'
& $python -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $python -c "import shutil; assert shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg tools are required on PATH'"
if ($LASTEXITCODE -ne 0) { throw 'FFmpeg tools are required.' }
& $python -m pytest tests -q "--junitxml=$release\tests.xml"
if ($LASTEXITCODE -ne 0) { throw 'Tests failed: EXE build has been stopped.' }
# Download/verify once, then perform real CPU translation before packaging.
& $python prepare_translation.py
if ($LASTEXITCODE -ne 0) { throw 'Local Arabic model setup or translation test failed. Build stopped.' }
& $python -m PyInstaller --noconfirm --clean --distpath "$release\dist" --workpath "$release\build" Veyora_Pro_onefile.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
$exe = Join-Path $release 'dist\Veyora-Pro-1.7.0-Windows-x64.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw 'Expected EXE missing.' }
$smoke = Join-Path $release 'exe_selftest.json'
# Test the actual packaged executable, dependencies, Tk, and bundled FFmpeg.
$process = Start-Process -FilePath $exe -ArgumentList @('--self-test', "`"$smoke`"") -PassThru
if (-not $process.WaitForExit(120000)) { $process.Kill(); throw 'Packaged EXE smoke test timed out.' }
if (-not (Test-Path -LiteralPath $smoke)) { throw 'Packaged EXE produced no self-test report.' }
$report = Get-Content -LiteralPath $smoke -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $report.ok) { throw "Packaged EXE self-test failed: $($report.error)" }
Write-Host "Built and smoke-tested: $exe"
Write-Host 'Test the new EXE with real site URLs before replacing your current installation or publishing this release.'
