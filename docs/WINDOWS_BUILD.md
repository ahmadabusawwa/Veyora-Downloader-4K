# Windows 10/11 x64 build and review

Use Python 3.12 x64, an official Inno Setup 6 installation, and an independently obtained and verified FFmpeg/ffprobe x64 build. Do not run executables from unreviewed sources. The environment used for development is Linux: no Setup.exe was produced or executed here.

```powershell
.\build_windows_2.ps1 -FfmpegDirectory C:\verified-tools\ffmpeg\bin
```

Place `ffmpeg.exe`, `ffprobe.exe`, and the exact build's `LICENSE.txt` in that directory. Include required notices/source or source offer as applicable to that specific build, its GPL/LGPL configuration and enabled codecs. The packaging script refuses to bundle FFmpeg without a notice, but a notice alone is not legal review. Review `LICENSES.md` and `MODEL_NOTICE.md`. Models are downloaded on first use and cached outside the installation; the build does not download them or bake them into the installer.

The script creates an isolated venv, installs requirements, executes tests, builds a PyInstaller onedir application and compiles Inno Setup. Output: `dist/setup/Veyora-Pro-2.0.3-Setup.exe`. Stable AppId and a per-user `{localappdata}/Programs/Veyora Pro` directory permit upgrades without administrator rights. User settings/history/models remain in `~/.veyora` (the 1.7 location). Uninstall only removes installed application files and shortcuts.

Run `tools/test_installer.ps1 -Setup PATH` only in an isolated CI worker with `CI=true`. It refuses an existing Veyora installation. It tests installation, same-version reinstall, the packaged native GUI, uninstall and settings/history/model sentinel preservation. It has not been executed in this Linux session. It does not establish a 1.7-to-2.0 migration or power-loss recovery result.

`.github/workflows/windows-review.yml` provides manually triggered or PR tests and GUI evidence. It has not been triggered remotely. No workflow publishes releases. FFmpeg integration tests require FFmpeg on PATH; provision a reviewed build on your runner. The lockfile is generated for Python 3.12 on Linux and must be revalidated on Windows; this is a reproducible recipe, not a claim of byte-identical Windows binaries.

Before approving distribution: run the Windows installer suite, test signed update fixtures in a disposable Windows build, verify all functions against the 1.7 feature catalog, inspect the native Windows screenshot against the reference, and test real consented public media and human speech samples.

`windows-installer-review.yml` is a separate manually triggered Setup build/test workflow for a disposable owner-provisioned self-hosted Windows runner labelled `veyora-review`. It does not fetch or execute arbitrary FFmpeg installers. It uses a provided reviewed directory and uploads a review artifact only, never a GitHub Release. This workflow has not been run in this session.
