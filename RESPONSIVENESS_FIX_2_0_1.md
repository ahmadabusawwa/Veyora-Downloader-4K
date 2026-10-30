# Veyora Pro 2.0.1 — responsiveness review

This follow-up addresses the installed-user report: slow speech progress, poor responsiveness while minimizing/clicking, and no clear click acknowledgement.

## Confirmed fixes

- The Start button previously retained its idle label while a job was running. It now immediately changes to Processing, disables duplicate submissions and editing of job inputs, and enables Cancel. Cancel immediately changes the visible state to Cancelling and disables repeated cancellation.
- Running/cancelling status is retained when switching away from the local-media screen and back. Completion restores controls on the UI thread.
- An indeterminate animation and elapsed time distinguish a running job from an idle screen. A worker heartbeat does not invent recognition progress or an ETA. Hidden-window progress rendering is deferred until restoration.
- Native AI processing has a CPU thread budget capped at half the logical CPUs (minimum one), instead of using all four threads on a four-logical-CPU machine. Only the child process receives below-normal Windows priority. Whisper beam size, model selection, video resolution and output quality settings are unchanged.
- This trades some processing throughput for desktop responsiveness. It does not guarantee faster recognition on weak hardware.

## Validation

- Linux/Xvfb: 167 passed, 3 skipped. New regression covers duplicate click prevention, immediate button states, cancellation, switching tabs while active, minimize/restore and UI timer ticks with a controlled waiting backend.
- Five targeted UI/performance tests also passed independently.
- Tests exercise the real window and a real spawned worker for the same-language SRT path. They do not reproduce the user's exact Windows hardware or certify continuous long-video speech recognition.
- An initial full local run was rejected by automatic review for a Microsoft telemetry attempt. The ONNX-backed model-selection unit test was corrected to mock native ONNX initialization because WhisperModel is already mocked there. The resulting 167-test run does not initialize an ONNX inference session. No blocked real-speech validation was retried or counted as passed.
- The sample screenshot showed recognition at 2 seconds out of 1058 seconds. That measures processed media position, not elapsed wall-clock time, and alone cannot establish a deadlock or an ETA.

The separate Windows review workflow builds version 2.0.1 and checks installed text translation/SRT/MP4 rendering. It does not validate speech recognition for the user's 17-minute clip. No official release is published.
