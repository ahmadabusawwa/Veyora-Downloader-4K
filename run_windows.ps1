$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot '.run-venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        & py -3.12 -m venv (Join-Path $PSScriptRoot '.run-venv')
        if ($LASTEXITCODE) { throw 'Python 3.12 x64 is required. Install it before running Veyora.' }
    }
    $lock = Join-Path $PSScriptRoot 'requirements-runtime.lock'
    $stamp = Join-Path $PSScriptRoot '.run-venv\dependencies.sha256'
    $digest = (Get-FileHash -LiteralPath $lock -Algorithm SHA256).Hash
    if (-not (Test-Path $stamp) -or (Get-Content $stamp -Raw).Trim() -ne $digest) {
        & $python -m pip install --require-hashes -r $lock
        if ($LASTEXITCODE) { throw 'Dependency installation failed. Check the error above and retry.' }
        Set-Content -LiteralPath $stamp -Value $digest -Encoding ascii
    }
    foreach ($dir in @((Join-Path $PSScriptRoot 'tools\ffmpeg\bin'), (Join-Path $PSScriptRoot 'ffmpeg\bin'))) {
        if ((Test-Path "$dir\ffmpeg.exe") -and (Test-Path "$dir\ffprobe.exe")) {
            $env:PATH = "$dir;$env:PATH"
            break
        }
    }
    & $python main.py
    if ($LASTEXITCODE) { throw 'Veyora exited with an error. The diagnostic message is shown above.' }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
