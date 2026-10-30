# Veyora Pro 2.0 — review build

Native Python desktop video downloader and local subtitle translator for Windows 10/11 x64. This is a development review build, **not an approved production release**. It extends the supplied 1.7 source; the original media engine, queue, history, site routing and translation modules are retained.

On Windows, double-click `RUN_VEYORA.cmd` to create an isolated environment, install the locked dependencies once and launch the application. Python 3.12 x64 is required. Setup building remains a separate operation.

## Run from source

Python 3.12, FFmpeg and ffprobe on PATH:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

Use `requirements-runtime.lock` for the recorded resolved runtime versions (Python 3.12/Linux); Windows resolution must be validated. The native GUI requires a desktop display. Models download on first use; subsequent sessions reuse verified model installations. Source builds do not require administrator privileges. No Windows installer is included in this source package.

## Main workflows

- Paste an HTTP(S) link, analyze it, choose quality/container/destination, and start downloading. Enable one-click download to enqueue without the format dialog. Playlists use the retained 1.7 selection workflow. The sidebar opens video/audio, local translation, conversion, files, settings and history.
- Download queue supports progress, speed/ETA, pause/resume, cancellation, retry and opening completed files. Cards update in place. Partial files are retained for resume; personal files are never broadly deleted.
- Choose speech source (`auto`, `ar`, `en`, `tr`, `ko`) and a different translation target. `separate`: SRT; `embed`: SRT plus MKV subtitle track; `burn`: SRT plus burned MP4; `both`: SRT plus MKV track. Final target SRT is exported by default; original source SRT is opt-in. Original transcripts remain cached for retry.
- Translation screen accepts local audio/video or UTF-8 SRT. For SRT select the source explicitly; speech auto-detection does not apply to text. Conversion supports MP4, MKV and MP3. Cancellation is cooperative between model operations and during FFmpeg processing.
- Advanced download controls retain the 1.7 subtitle selection, audio format, smart mode and folder controls. Settings retains cookies, concurrent downloads and subtitle preferences. Use only cookies for content you are entitled to access. DRM circumvention is not implemented.
- Settings offers economy/balanced/high CPU and concurrency budgets, base/small/medium speech models, update checks and explicit prerelease opt-in. Larger speech models consume more RAM and may take longer; their quality is not certified here.

## Updates and Windows Setup

See [update security](docs/UPDATE_SECURITY.md) and [Windows build](docs/WINDOWS_BUILD.md).

The signed updater is implemented and tested against safe inert fixtures. **Production trust is intentionally disabled** until the owner installs a public Ed25519 signing key. It will not execute an unsigned or unverifiable update. The owner must keep the private key offline. The first upgrade from 1.7 is manual because 1.7 has no updater.

```powershell
.\build_windows_2.ps1 -FfmpegDirectory C:\verified-tools\ffmpeg\bin
```

Produces `Veyora-Pro-Setup-2.0.0.exe` on Windows after passing checks. Inno Setup installs per user, creates shortcuts and an uninstaller, and leaves `.veyora`, downloaded media and model files outside the application directory. This Linux session did not build or execute a Windows installer. Cross-version update, uninstall and power-loss testing remain mandatory.

## Validation actually performed

```bash
python -m pytest tests -q --junitxml=review-tests.xml
node --test tests/release.test.cjs
python tools/inference_matrix.py
python tools/speech_matrix.py  # needs espeak-ng; synthetic speech integration only
python tools/gui_smoke.py --output gui-review.png
python tools/gui_download_test.py
python -m pip_audit -r requirements.txt -f json -o dependency-audit.json
```

See [review report](docs/REVIEW_2_0.md) for exact results, limitations and unfinished work. Text inference ran in all 12 directions; this does not establish speech or translation accuracy. Synthetic Arabic recognition failed, and Turkish/Korean recognition showed errors. No claim is made that all sites, all audio, 4K workflows or Windows installation are verified.

## Privacy and licenses

Settings, history, models and transcript caches are local under `~/.veyora` or `VEYORA_CONFIG_DIR`. Downloads use the chosen folder. Update checks contact GitHub; media downloads contact their source sites; first-use models contact their hosts. Translation inference is local. Diagnostic URL credentials/query values are redacted and yt-dlp's unsolicited diagnostic logger is suppressed. History intentionally contains the source URL; treat that local file as private.

See [third-party notices](LICENSES.md) and [model notice](MODEL_NOTICE.md). No blanket commercial redistribution clearance is claimed. FFmpeg build options and model/data licenses need review before publishing. The source baseline is saved in local Git commit `e513ce9`; development uses a separate branch. No official release has been published.
