param([string]$Application,[string]$ConfigDirectory,[string]$Media,[string]$OutputDirectory)
$ErrorActionPreference='Stop'
if ($env:CI -ne 'true' -or $env:VEYORA_REVIEW_NETWORK_BLOCKED -ne '1') { throw 'Verified disposable firewall scope required' }
$Application=(Resolve-Path $Application).Path
$OutputDirectory=[IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force $OutputDirectory | Out-Null
$profile=Join-Path $env:RUNNER_TEMP ('veyora-regression-'+[guid]::NewGuid())
New-Item -ItemType Directory -Force $profile | Out-Null
'{"auto_update_check":false,"ui_language":"ar","speech_model":"base","save_original_subtitles":true}' | Set-Content -Encoding utf8NoBOM (Join-Path $profile 'settings.json')
New-Item -ItemType Junction -Path (Join-Path $profile 'models') -Target (Join-Path $ConfigDirectory 'models') | Out-Null
$savedConfig=$env:VEYORA_CONFIG_DIR;$savedAudit=$env:VEYORA_REVIEW_AUDIT_DIR;$savedAssociation=$env:VEYORA_REVIEW_VIDEO_ASSOCIATION
$association='HKCU:\Software\Classes\.mp4';$programId='VeyoraDisposableReview'+[guid]::NewGuid().ToString('N')
$programKey='HKCU:\Software\Classes\'+$programId
$associated=$false;$keyExisted=Test-Path $association;$priorDefault=$null
try {
 $env:VEYORA_CONFIG_DIR=$profile;$env:VEYORA_REVIEW_AUDIT_DIR=Join-Path $OutputDirectory 'audit';$env:VEYORA_REVIEW_VIDEO_ASSOCIATION='0'
 $player=Join-Path $env:VEYORA_FFMPEG_DIR 'ffplay.exe'
 if ((Test-Path $player) -and -not (Test-Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.mp4\UserChoice')) {
  if ($keyExisted) { $priorDefault=(Get-Item $association).GetValue('') }
  New-Item -Path $association -Force | Out-Null
  New-Item -Path ($programKey+'\shell\open\command') -Force | Out-Null
  Set-Item -Path ($programKey+'\shell\open\command') -Value ('"'+$player+'" -autoexit -loglevel error "%1"')
  Set-Item -Path $association -Value $programId
  $associated=$true;$env:VEYORA_REVIEW_VIDEO_ASSOCIATION='1'
 }
 $p=Start-Process -FilePath $Application -ArgumentList @('--review-regression-recovery',"`"$Media`"","`"$OutputDirectory`"") -PassThru
 if (-not $p.WaitForExit(240000)) { & taskkill.exe /PID $p.Id /T /F | Out-Null;throw 'Native regression review timeout' }
 $report=Get-Content -Raw -LiteralPath (Join-Path $OutputDirectory 'regression-results.json') | ConvertFrom-Json
 Write-Host ('REGRESSION_REPORT '+($report | ConvertTo-Json -Depth 15 -Compress))
 if ($p.ExitCode -ne 0 -or -not $report.ok) { throw 'Actual installed/portable regression review failed' }
} finally {
 if ($associated) {
  if ($null -ne $priorDefault) { Set-Item -Path $association -Value $priorDefault }
  elseif ($keyExisted) { (Get-Item $association).DeleteValue('',$false) }
  else { Remove-Item $association }
  Remove-Item $programKey -Recurse -Force
 }
 Get-CimInstance Win32_Process -Filter "name = 'ffplay.exe'" | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($OutputDirectory) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
 $env:VEYORA_CONFIG_DIR=$savedConfig;$env:VEYORA_REVIEW_AUDIT_DIR=$savedAudit;$env:VEYORA_REVIEW_VIDEO_ASSOCIATION=$savedAssociation
}
