param(
 [Parameter(Mandatory=$true)][string]$Application,
 [Parameter(Mandatory=$true)][string]$ConfigDirectory,
 [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference='Stop'
if ($env:CI -ne 'true') { throw 'Run only in a disposable Windows CI worker.' }
$Application=(Resolve-Path -LiteralPath $Application).Path
$OutputDirectory=[IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force $OutputDirectory | Out-Null
$fixtures=Join-Path $OutputDirectory 'fixtures'
New-Item -ItemType Directory -Force $fixtures | Out-Null
$wave=Join-Path $fixtures 'speech.wav'
$voice=New-Object -ComObject SAPI.SpVoice
$stream=New-Object -ComObject SAPI.SpFileStream
try {
 $english=$voice.GetVoices('Language=409')
 if ($english.Count -eq 0) { throw 'A local English desktop SAPI voice is required.' }
 $voice.Voice=$english.Item(0)
 $voice.Rate=-1
 $stream.Open($wave,3,$false)
 $voice.AudioOutputStream=$stream
 $text='Hello world. Today the weather is beautiful. Please download this video and save the subtitles.'
 $voice.Speak($text) | Out-Null
 $description=$voice.Voice.GetDescription()
} finally {
 $stream.Close()
 [void][Runtime.InteropServices.Marshal]::ReleaseComObject($stream)
 [void][Runtime.InteropServices.Marshal]::ReleaseComObject($voice)
}
$ffmpeg=Join-Path $env:VEYORA_FFMPEG_DIR 'ffmpeg.exe'
$video=Join-Path $fixtures 'فيديو تجريبي.mp4'
$cancelVideo=Join-Path $fixtures 'فيديو الإلغاء.mp4'
& $ffmpeg -nostdin -y -v error -f lavfi -i 'color=c=blue:s=320x180:r=15:d=90' -stream_loop -1 -i $wave -t 90 -c:v libx264 -threads 2 -pix_fmt yuv420p -c:a aac $video
if ($LASTEXITCODE) { throw 'Real speech video creation failed' }
& $ffmpeg -nostdin -y -v error -stream_loop 2 -i $video -t 180 -c copy -metadata comment=independent-cancellation-fixture $cancelVideo
if ($LASTEXITCODE) { throw 'Cancellation speech video creation failed' }
@{scope='Local synthetic desktop SAPI speech, no external media';voice=$description;text=$text} | ConvertTo-Json | Set-Content -Encoding utf8NoBOM (Join-Path $fixtures 'NOTICE.json')

# Deny outbound traffic by executable before any native speech inference runs.
# This applies to the frozen child workers too, which use the same executable.
$disabled=@(Get-NetFirewallProfile | Where-Object { -not $_.Enabled })
if ($disabled.Count) { throw 'Firewall profiles must already be enabled for native offline validation.' }
$prefix='Veyora-Review-'+[guid]::NewGuid().ToString()
$programs=@($Application)
$programs+=@(Get-ChildItem -LiteralPath (Split-Path $Application) -Recurse -File | Where-Object { $_.Name -in @('ffmpeg.exe','ffprobe.exe') } | ForEach-Object { $_.FullName })
$names=@()
$policy=New-Object -ComObject HNetCfg.FwPolicy2
try {
 $verified=@()
 foreach ($program in $programs) {
  $name=$prefix+'-'+$names.Count
  Write-Host ('Creating native outbound block for '+$program)
  if (-not [IO.Path]::IsPathFullyQualified($program) -or -not (Test-Path -LiteralPath $program)) { throw 'Firewall program path is not a real absolute executable path' }
  $rule=New-Object -ComObject HNetCfg.FWRule
  $rule.Name=$name
  $rule.ApplicationName=$program
  $rule.Protocol=256
  $rule.Direction=2
  $rule.Action=0
  $rule.Profiles=2147483647
  $rule.InterfaceTypes='All'
  $rule.Enabled=$true
  $policy.Rules.Add($rule)
  $names+=$name
  $check=$policy.Rules.Item($name)
  if (-not $check.Enabled -or $check.Direction -ne 2 -or $check.Action -ne 0 -or $check.ApplicationName -ne $program -or $check.Profiles -ne 2147483647) {
   throw 'Native program firewall isolation was not verified'
  }
  $verified+=@{name=$check.Name;program=$check.ApplicationName;enabled=$check.Enabled;direction='Outbound';action='Block';all_profiles=($check.Profiles -eq 2147483647)}
 }
 @{programs=$programs;rules=$verified;profiles=@(Get-NetFirewallProfile | Select-Object Name,Enabled)} | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8NoBOM (Join-Path $OutputDirectory 'firewall-evidence.json')
 $env:HF_HUB_OFFLINE='1'
 $env:VEYORA_CONFIG_DIR=$ConfigDirectory
 $env:VEYORA_REVIEW_NETWORK_BLOCKED='1'
 # Settings changes are confined to the disposable test user-data directory.
 $settings=Join-Path $ConfigDirectory 'settings.json'
 $before=[IO.File]::ReadAllBytes($settings)
 try {
  @{auto_update_check=$false;ui_language='en';speech_model='base';save_original_subtitles=$true;performance_mode='balanced'} | ConvertTo-Json | Set-Content -Encoding utf8NoBOM $settings
  $args=@('--review-video',"`"$video`"","`"$cancelVideo`"","`"$OutputDirectory`"")
  $p=Start-Process -FilePath $Application -ArgumentList $args -PassThru
  if (-not $p.WaitForExit(660000)) {
   & taskkill.exe /PID $p.Id /T /F | Out-Null
   throw 'Actual installed speech/video GUI test timed out'
  }
  $result=Join-Path $OutputDirectory 'real-video-results.json'
  if (-not (Test-Path $result)) { throw 'Actual video report was not produced' }
  $report=Get-Content -LiteralPath $result -Raw | ConvertFrom-Json
  if ($p.ExitCode -ne 0 -or -not $report.ok) { throw ('Actual video validation failed: '+($report.errors -join '; ')) }
  Write-Host ('REAL_VIDEO_REPORT: '+($report | ConvertTo-Json -Depth 12 -Compress))
  Write-Host ('PASS actual installed video recognition, translation, SRT, MP4, minimize/maximize, cancellation. UI max gap: '+$report.ui_timer.max_gap_seconds)
 } finally { [IO.File]::WriteAllBytes($settings,$before) }
} finally {
 foreach ($name in $names) { try { $policy.Rules.Remove($name) } catch { Write-Warning "Could not remove disposable test rule $name" } }
 Remove-Item Env:VEYORA_REVIEW_NETWORK_BLOCKED -ErrorAction SilentlyContinue
}
