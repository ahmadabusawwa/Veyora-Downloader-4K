# Veyora Downloader 4K 🚀

`Python 3.12+` | `CustomTkinter` | `yt-dlp` | `FFmpeg` | `Windows`

**Professional 4K Media Downloader & Transcoding Studio** built with Python 3.12, CustomTkinter, and yt-dlp.
---

## ✨ Features / المميزات

### 🇬🇧 English
- **Modern Dashboard & Sidebar Navigation**: Sleek user interface supporting both Dark and Light UI modes.
- **Universal Media Downloading**: Extract and download high-quality media from YouTube, Vimeo, TikTok, and hundreds of other platforms.
- **Ultra-HD & Quality Control**: Select 4K, 1080p, 720p, or set to automatic highest available resolution.
- **Audio Extraction**: Convert videos to high-fidelity MP3 or M4A audio with custom bitrate options.
- **Playlists & Channels Batch Download**: Seamlessly process and download full playlists or entire channel archives in batch mode.
- **Automatic Subtitles & Thumbnails Archiver**: Embedded and standalone subtitle & thumbnail saving support.
- **Concurrent Queue Manager**: Real-time download speed tracking, remaining time estimator, and visual progress indicators.
- **Persistent Settings & History**: Save custom preferences and review download history locally.
---
### ⚠️ Note: FFmpeg Installation Required

**FFmpeg must be installed before using Veyora Pro.** If FFmpeg is not already installed, follow these steps:

1. Open **PowerShell as Administrator**.
2. Run the following command to install FFmpeg using Winget:

```powershell
winget install --id Gyan.FFmpeg.Shared -e
```

3. Restart PowerShell and verify the installation:

```powershell
ffmpeg -version
```

4. Once installed, launch `Veyora Pro.exe`.

**Important:** If `winget` is unavailable, install FFmpeg manually and add its `bin` folder to your system's PATH environment variable.
