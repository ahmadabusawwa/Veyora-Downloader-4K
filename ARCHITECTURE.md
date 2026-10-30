> Historical document supplied with 1.7. Its completion/testing claims are not validated by this session. Use docs/REVIEW_2_0.md and current code for 2.0 status.

# NexusStream Pro — Architecture & Design Document

## Architecture Overview
NexusStream Pro is engineered with a modular Python 3.12 architecture separating the GUI presentation layer, core download orchestration engine, yt-dlp wrapper wrapper, and persistent storage.

```
nexus_stream_pro/
│
├── main.py                # Entry point & application lifecycle
├── requirements.txt       # Python dependencies
├── README.md              # User documentation
├── ARCHITECTURE.md        # This architecture document
├── FEATURE_CATALOG.md     # Discovered feature inventory
├── FEATURE_TRACEABILITY.md# Feature implementation mapping
├── TEST_REPORT.md         # Verification test results
├── LICENSES.md            # Third-party notices
│
├── core/
│   ├── __init__.py
│   ├── engine.py          # yt-dlp wrapper, download worker, progress callback
│   ├── queue.py           # Concurrent download task queue & threadpool
│   ├── config.py          # Persistent settings (JSON) & history store
│   └── extractor.py       # URL info inspection (video, playlist, channel parser)
│
└── ui/
    ├── __init__.py
    ├── app.py             # CustomTkinter main window & navigation
    ├── dashboard.py       # Dashboard view & quick URL input
    ├── downloads.py       # Active downloads & queue management view
    ├── history.py         # Completed downloads history view
    ├── settings.py        # Application settings view
    └── dialogs.py         # Format/Quality selection & batch dialogs
```

## Core Modules & Design Patterns

1. **Engine (`core/engine.py`)**
   - Integrates `yt-dlp` programmatically with custom progress hooks.
   - Handles video, audio extraction (MP3/M4A), subtitle downloading, and thumbnail extraction.
   - Detects FFmpeg availability for automatic merging and transcoding.

2. **Queue Manager (`core/queue.py`)**
   - Multi-threaded task queue supporting configurable concurrency (1 to 8 concurrent downloads).
   - Provides thread-safe pause, resume, cancel, and retry capabilities.

3. **Configuration & History (`core/config.py`)**
   - Persists user preferences and completed download records in local JSON files (`settings.json`, `history.json`).

4. **UI (`ui/app.py` & views)**
   - Built with `customtkinter` for a polished, modern dark/light desktop experience.
   - Uses background worker threads (`threading.Thread`) to keep the UI fully responsive during heavy network transfers.
