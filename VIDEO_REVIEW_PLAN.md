# 2.0.1 real installed-video review

The previous working source is preserved at `backup/veyora-2.0.1-before-video-review-20261030` (commit `0deaa5fbf4165adc69cb6eec17529e9dfff60a79`). The workflow preserves the previous Setup from successful run 41084220503 into the new artifact's `backups/` directory before building.

The new development branch tests the **installed executable**, using synthetic local English SAPI speech in a 90-second blue video. Automation invokes the actual local-media GUI Start button, uses real faster-whisper/CTranslate2 inference, and burns real Arabic subtitles with FFmpeg. It checks the recognized English keywords, translated Arabic keywords, SRT timestamps, output video/audio streams/duration, and visible subtitle pixels in a sampled frame. Synthetic speech is not a certification of arbitrary human audio quality.

During actual processing it exercises minimize, restore, maximize and restore again while recording the 50 ms GUI timer's measured gaps. A different 180-second video forces fresh speech recognition; Cancel is invoked only after a real recognized-segment progress event. Cleanup verifies no multiprocessing worker remains alive.

Models are downloaded before the audio test. The speech test then runs with `HF_HUB_OFFLINE=1` and verified outbound block rules on the installed executable and bundled FFmpeg programs, with already-enabled Windows Firewall profiles. Frozen child workers use the same blocked executable. The rules are removed in a finally block. This prevents a native dependency from sending telemetry during the real speech test. Native inference is never replaced by a mock in this review.

Results and example SRT/MP4 files are written under `real-video-review/`. The workflow must fail if any required check fails. Building an EXE alone is not a pass. No official release or main-branch update is performed.
