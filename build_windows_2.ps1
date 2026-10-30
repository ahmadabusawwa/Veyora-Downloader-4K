param([string]$FfmpegDirectory=$env:VEYORA_FFMPEG_DIR)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($env:OS -ne 'Windows_NT') { throw 'Windows x64 required.' }
if (-not $FfmpegDirectory) {
    $candidates = @((Join-Path $PSScriptRoot 'tools\ffmpeg\bin'), (Join-Path $PSScriptRoot 'ffmpeg\bin'))
    $command = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
    if ($command) { $candidates += (Split-Path $command.Source) }
    foreach ($candidate in $candidates) {
        if ((Test-Path "$candidate\ffmpeg.exe") -and (Test-Path "$candidate\ffprobe.exe")) {
            $FfmpegDirectory = $candidate
            break
        }
    }
}
if (-not $FfmpegDirectory) {
    throw 'FFmpeg was not found. To RUN Veyora, open RUN_VEYORA.cmd. To BUILD Setup, provide -FfmpegDirectory with the folder containing ffmpeg.exe and ffprobe.exe.'
}
foreach ($name in @('ffmpeg.exe', 'ffprobe.exe')) {
    if (-not (Test-Path -LiteralPath (Join-Path $FfmpegDirectory $name))) { throw "Missing $name in the selected FFmpeg directory." }
}
if (-not (Test-Path -LiteralPath (Join-Path $FfmpegDirectory 'LICENSE.txt'))) {
    throw 'FFmpeg binaries were found, but their redistribution notice LICENSE.txt is missing. Include the original notice for this exact build before packaging.'
}
$env:VEYORA_FFMPEG_DIR=(Resolve-Path $FfmpegDirectory).Path
py -3.12 -m venv .build-venv
if ($LASTEXITCODE) { throw 'Python venv failed' }
$python='.build-venv\Scripts\python.exe'
& $python -m pip install --require-hashes -r requirements-runtime.lock
if ($LASTEXITCODE) { throw 'Locked runtime dependencies failed' }
& $python -m pip install -r requirements-build.txt
if ($LASTEXITCODE) { throw 'Dependencies failed' }
$env:PATH="$env:VEYORA_FFMPEG_DIR;$env:PATH"
& $python -m pytest tests -q --junitxml=windows-tests.xml
if ($LASTEXITCODE) { throw 'Tests failed' }
& $python -m PyInstaller --noconfirm --clean packaging/Veyora-Pro.spec
if ($LASTEXITCODE) { throw 'Packaging failed' }
$iscc=Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $iscc) {
 $path = @('C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
           'C:\Program Files\Inno Setup 6\ISCC.exe',
           'C:\Program Files\Inno Setup 7\ISCC.exe') | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
 if (-not $path) { throw 'Install Inno Setup 6 or 7 from the official source first.' }
} else { $path=$iscc.Source }
& $path packaging/installer.iss
if ($LASTEXITCODE) { throw 'Inno Setup failed' }
Write-Host 'Review artifact: dist\setup\Veyora-Pro-2.0.3-Setup.exe. No release was published.'
