# Veyora Downloader 4K

`Python 3.12+` | `CustomTkinter` | `yt-dlp` | `FFmpeg (Required)` | `Windows` | `MIT License`

## Overview
**Veyora Downloader 4K** is a modern, open-source desktop application designed for downloading high-definition videos up to 4K resolution and extracting high-fidelity audio streams. Built using Python 3.12, CustomTkinter, yt-dlp, and FFmpeg, Veyora offers a fast, reliable, and user-friendly experience for managing media downloads across hundreds of web platforms.

## Key Features
- **Ultra-HD 4K & Quality Control**: Download videos seamlessly in 4K, 1080p, 720p, and other resolutions with automatic video and audio merging powered by FFmpeg.
- **Universal Platform Support**: Extract media from YouTube, Vimeo, TikTok, and hundreds of other platforms supported natively by `yt-dlp`.
- **High-Fidelity Audio Extraction**: Extract audio streams in popular formats including MP3 and M4A with customizable bitrate selection and metadata tagging via `mutagen`.
- **Playlists & Batch Downloading**: Download complete playlists, channels, and batch video queues effortlessly.
- **Subtitles & Thumbnails**: Automatically fetch and embed subtitles and high-resolution thumbnail images into downloaded files.
- **Concurrent Queue Manager**: Manage multiple ongoing downloads with real-time speed monitoring, estimated time remaining (ETA), and progress indicators.
- **Modern Flicker-Free UI**: Enjoy a sleek dark/light theme switcher built with `CustomTkinter`, complete with keyboard shortcuts, configuration persistence, and download history management.

## Mandatory Requirement: FFmpeg Installation

> **Important:** **FFmpeg is strictly required** for Veyora Downloader 4K to function properly. High-resolution streams (4K/1080p) require FFmpeg to merge separate video and audio tracks and to convert audio into MP3/M4A formats.

Follow the steps below to install **FFmpeg** on Windows before running the application:

### Method 1: Quick Install via Windows Terminal / PowerShell (Recommended)
1. Open **PowerShell** or **Command Prompt** as Administrator.
2. Run the following command using **Winget** (built into Windows 10/11):
   ```powershell
   winget install Gyan.FFmpeg
   ```
   *(Alternatively, if you use Chocolatey or Scoop)*:
   ```powershell
   choco install ffmpeg
   # OR
   scoop install ffmpeg
   ```
3. **Restart** your terminal (and restart Veyora if it is already open) so the system `PATH` updates automatically.
4. **Verify Installation**: Run the command below to confirm FFmpeg is installed and recognized:
   ```powershell
   ffmpeg -version
   ```

### Method 2: Manual Setup (Portable)
1. Download the latest Windows release build (`ffmpeg-release-essentials.zip`) from the official FFmpeg builds page.
2. Extract the archive and open the `bin` folder.
3. Copy `ffmpeg.exe` and `ffprobe.exe` and place them directly in the **same folder as `Veyora.exe`** (or add the `bin` folder path to your Windows Environment Variables `PATH`).

## Tech Stack & Dependencies
The project relies on modern Python technologies and powerful open-source media engines:

| Dependency | Required Version | Description |
| :--- | :--- | :--- |
| **FFmpeg** | `Latest (Mandatory)` | Video/audio transcoding and stream merging engine |
| **CustomTkinter** | `>=5.2.0` | Modern UI toolkit for Tkinter |
| **yt-dlp** | `>=2025.0.0` | Media extraction engine |
| **requests** | `>=2.31.0` | HTTP network communication library |
| **mutagen** | `>=1.47.0` | Audio metadata tagging library |
| **Pillow** | `>=10.0.0` | Image processing library for thumbnail rendering |
| **darkdetect** | `>=0.8.0` | OS theme detection utility |
| **certifi** | `>=2023.5.7` | SSL certificate authority bundle |

## Usage & Keyboard Shortcuts
1. **Paste Link**: Copy a video or playlist URL into the input field (`Ctrl + V`).
2. **Select Format & Quality**: Choose your preferred resolution (4K, 1080p, 720p) or select Audio-only (MP3/M4A).
3. **Download**: Click the **Download** button or press `Enter` to start downloading.

### Useful Keyboard Shortcuts
- `Ctrl + V`: Paste URL from clipboard.
- `Enter`: Trigger media download.
- `Ctrl + D`: Switch between Dark and Light mode.
- `Ctrl + C`: Cancel active download queue.

## Troubleshooting / FAQ & License

### Common Issues & Troubleshooting
- **FFmpeg Not Detected**: Run `ffmpeg -version` in Command Prompt to verify it is in your `PATH`, or place `ffmpeg.exe` and `ffprobe.exe` directly inside the application directory alongside `Veyora.exe`.
- **Merged Video Has No Audio**: This occurs if FFmpeg is missing. Install FFmpeg using `winget install Gyan.FFmpeg` and restart the program.

### Contributing
Contributions, issues, and feature requests are welcome! Feel free to check the Issues tab in [Veyora-Downloader-4K](https://github.com/ahmadabusawwa/Veyora-Downloader-4K).

### License
This project is licensed under the MIT License.