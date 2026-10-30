param([Parameter(Mandatory=$true)][string]$Setup)
$ErrorActionPreference='Stop'
if ($env:CI -ne 'true') { throw 'Run only on an isolated disposable Windows CI worker.' }
$existing='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{CB5D7202-462E-4BDF-A6BD-92449F02E003}_is1'
if (Test-Path $existing) { throw 'Existing Veyora installation detected; refusing to alter it.' }
$root=Join-Path $env:RUNNER_TEMP ('veyora-install-test-'+[guid]::NewGuid())
$install=Join-Path $root 'application'
$data=Join-Path $root 'user-data'
New-Item -ItemType Directory -Path $data -Force | Out-Null
$env:VEYORA_CONFIG_DIR=$data
'{"auto_update_check":false,"sentinel":"preserve-me"}' | Set-Content -Encoding utf8NoBOM (Join-Path $data 'settings.json')
'[{"sentinel":"history"}]' | Set-Content -Encoding utf8NoBOM (Join-Path $data 'history.json')
New-Item -ItemType Directory -Path (Join-Path $data 'models') | Out-Null
'preserve-model' | Set-Content (Join-Path $data 'models\sentinel')
if (-not $env:VEYORA_TEST_MODELS -or -not (Test-Path -LiteralPath $env:VEYORA_TEST_MODELS)) {
 throw 'Prepare verified translation models first and set VEYORA_TEST_MODELS to the models directory.'
}
Copy-Item -Path (Join-Path $env:VEYORA_TEST_MODELS '*') -Destination (Join-Path $data 'models') -Recurse -Force
$env:HF_HUB_OFFLINE='1'
$legacy='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{9A49F650-703B-4B27-A053-964BE220E4AA}_is1'
if (Test-Path $legacy) { throw 'Unexpected pre-existing legacy app on the disposable worker' }
$oldInstall=Join-Path $root 'previous-application'
$oldSetup=Join-Path $PSScriptRoot '..\backups\Veyora-Pro-Setup-2.0.2-previous.exe'
$p=Start-Process -FilePath (Resolve-Path $oldSetup) -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/DIR=`"$oldInstall`"") -PassThru -Wait
if ($p.ExitCode -ne 0) { throw 'Previous version backup installation failed' }
$oldHash=Get-FileHash "$oldInstall\Veyora-Pro.exe"
$before=Get-FileHash (Join-Path $data 'settings.json')
foreach ($attempt in 1,2) {
 $p=Start-Process -FilePath (Resolve-Path $Setup) -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/DIR=`"$install`"") -PassThru -Wait
 if ($p.ExitCode -ne 0) { throw "Setup failed: $($p.ExitCode)" }
 if (-not (Test-Path "$install\Veyora-Pro.exe")) { throw 'Executable missing' }
}
$p=Start-Process -FilePath "$install\Veyora-Pro.exe" -ArgumentList @('--gui-smoke',"`"$root\gui.png`"") -PassThru
if (-not $p.WaitForExit(60000)) { $p.Kill();throw 'Packaged GUI test timeout' }
if ($p.ExitCode -ne 0 -or -not (Test-Path "$root\gui.png")) { throw 'Packaged GUI smoke failed' }
$selfReport=Join-Path $root 'installed-translation.json'
$p=Start-Process -FilePath "$install\Veyora-Pro.exe" -ArgumentList @('--self-test',"`"$selfReport`"") -PassThru
if (-not $p.WaitForExit(180000)) { $p.Kill();throw 'Installed translation test timeout' }
if ($p.ExitCode -ne 0 -or -not (Test-Path $selfReport)) { throw 'Installed translation test failed' }
$report=Get-Content -LiteralPath $selfReport -Raw | ConvertFrom-Json
if (-not $report.ok -or -not $report.srt_translation_and_mp4_render) { throw 'Installed translation report did not confirm success' }
Copy-Item -LiteralPath $selfReport -Destination (Join-Path $PSScriptRoot '..\installed-translation.json') -Force
# Actual audio-to-Arabic video test, driven through installed GUI commands.
$reviewSettings=[IO.File]::ReadAllBytes((Join-Path $data 'settings.json'))
try {
 & (Join-Path $PSScriptRoot 'real_video_review.ps1') -Application "$install\Veyora-Pro.exe" -ConfigDirectory $data -OutputDirectory (Join-Path $PSScriptRoot '..\real-video-review')
} finally { [IO.File]::WriteAllBytes((Join-Path $data 'settings.json'),$reviewSettings) }
$p=Start-Process -FilePath "$install\unins000.exe" -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') -PassThru -Wait
if ($p.ExitCode -ne 0) { throw 'Uninstall failed' }
if ((Get-FileHash "$data\settings.json").Hash -ne $before.Hash) { throw 'Settings changed' }
foreach ($name in @('history.json','models\sentinel')) { if (-not (Test-Path "$data\$name")) { throw "Lost user file: $name" } }
if (-not (Test-Path "$oldInstall\Veyora-Pro.exe") -or (Get-FileHash "$oldInstall\Veyora-Pro.exe").Hash -ne $oldHash.Hash -or -not (Test-Path $legacy)) { throw 'The review installer/uninstaller changed the previous installed version' }
$p=Start-Process -FilePath "$oldInstall\unins000.exe" -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') -PassThru -Wait
if ($p.ExitCode -ne 0) { throw 'Disposable previous-version cleanup failed' }
Write-Host 'PASS: previous Setup backup, side-by-side install, unchanged previous EXE hash, cached navigation, real playlist downloads, real speech translation, 20 minimize/restore cycles, cancellation, uninstall, preserved data.'

# Cross-version migration, installer cancellation and power-loss recovery need separate Windows runs.
