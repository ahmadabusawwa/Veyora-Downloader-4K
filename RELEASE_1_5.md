# 1.5.0 — render progress and lower-memory processing

## Changes

- FFmpeg `-progress pipe:1` is drained continuously by a reader thread. A bounded queue holds only the latest status packet; logs do not accumulate in memory.
- Burn and embed report actual media position divided by probed duration, measured encoding speed, and estimated remaining time. Missing duration/speed shows estimating rather than a fabricated number. Progress reaches 100% only after FFmpeg exits successfully. Copying the completed video is a separate saving stage.
- Native downloaded-caption burn follows the same progress path. Existing stable cards update their labels/progress without reconstruction.
- Burn uses two decoder threads, one filter thread, two encoder threads, `veryfast` x264 preset, lookahead 4, sync-lookahead 0 and two references. No explicit resolution/frame-rate reduction was introduced; CRF remains 20. Different encoder settings can change quality/size and can be slower on some processors.
- One heavy pipeline runs at a time; other downloads can continue. Waiting pipelines display a waiting state and can be cancelled. The same reentrant gate guards application-managed FFmpeg to avoid overlapping heavy stages.
- Speech weights unload after recognition; text translation weights unload before rendering. Final cleanup runs on failure/cancellation too. Model files stay on disk and are loaded again when needed, without re-downloading verified installed models.
- Speech inference CPU threads capped at four. This is not a hard process memory cap; native libraries/allocators can retain baseline memory.

## Executed memory measurements

Synthetic 1920x1080 /30 fps /6-second clip with identical subtitle filter and CRF20; Linux, isolated FFmpeg child per measurement using resource.getrusage(RUSAGE_CHILDREN). Both baseline and new renderer use two decoder threads and one filter thread. Baseline medium/8 encoder threads; new veryfast/2 encoder threads.

| Mode | Peak FFmpeg RSS MiB | Wall seconds |
| --- | ---: | ---: |
| Baseline medium, 8 threads | 607.8 | 4.73 |
| New veryfast, 2 threads | 195.4 | 5.09 |

This is about 68% less peak encoder memory on this sample, with a small runtime increase. It does not predict exact memory on the user's 4K clip or Windows computer. The earlier program used automatic thread count, which is hardware dependent; eight threads is the explicit comparison baseline, not a claim to reproduce every prior device setting.

Separate English→Arabic model measurement: Python RSS 20.3 MiB before imports/model; 149.1 MiB after load/inference; 97.1 MiB after native unload and collection. Shared library/allocator memory remains resident. Raw measurements are in benchmarks/.

## Verification and limits

See TEST_REPORT.md and tests-results.xml for executed checks. No Windows 1.5 EXE was built here; build_windows.ps1 builds into a new Veyora_Pro_1_5_0 release and verifies it on Windows. Real long-video ETA stability and memory on the user's device need confirmation. ETA is an estimate and changes with encode complexity and processor load. No GPU acceleration or universal fixed RAM ceiling is claimed.
