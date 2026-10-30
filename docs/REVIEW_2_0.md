# Veyora Pro 2.0 development review — 2026-10-30

**Status: functional development build, not production approved.** Source, native UI, secure updater components, build recipes and evidence are provided. A production signing key, Windows Setup build/testing, visual/RTL completion and speech quality work remain blockers. No official release was published, no user files were deleted, and the uploaded 1.7 ZIP was left unchanged.

## Source examined and preserved

The GitHub default branch initially contained the website, README, requirements and website tests, but no desktop Python source. The supplied `Veyora_Pro_1_7(2).zip` contains the desktop project plus a historical Windows venv/release directory (12,433 archive entries). Only project source/assets/tests/docs were safely extracted; the bundled environment/executables were neither executed nor added to the project. Git baseline commit `e513ce9` preserves that source, on separate development branch `development/veyora-2-review`. The previous third-party feature catalog and unsupported completion reports were not treated as evidence; historical reports are marked accordingly.

## Implemented and changed

| Area | Concrete change | Limit |
|---|---|---|
| Updates | Background startup/manual check; proper version ordering; stable/prerelease policy; release notes; bounded/cancellable progress download; signed Ed25519 metadata; size/hash verification; consent; parent-exit/reverification helper; backup/journal/retry notice | Trust store deliberately empty until owner enrollment. Windows handoff/install not run. No transactional binary rollback |
| Installer | PyInstaller onedir spec; Inno Setup per-user stable AppId; shortcuts/uninstall; data outside installation; explicit FFmpeg license prerequisite | Setup.exe not built on Linux. Installed 1.7 portable version needs manual bootstrap. Windows license/native dependency review pending |
| Desktop | Actual CustomTkinter dark/blue shell using reference layout; top navigation/sidebar; preview/options/queue panels; original line icons; responsive reflow; main Arabic/English navigation; native local translation/conversion | Not a pixel-exact replica. Some settings, dialogs, language/mode values and queue messages remain English. Full RTL/keyboard/accessibility/Windows visual review incomplete |
| Download | Reuse existing yt-dlp routing/Pinterest short links, format/audio/playlist selection, retry/resume/concurrency, progress/ETA and error handling; budgeted fragment concurrency; retained advanced controls | Live Pinterest/popular sites not verified; no guaranteed speed improvement or universal site support |
| Translation | All 12 existing routes retained; speech auto detection; explicit source/target controls; local media/SRT input; final-only SRT default and optional original transcript; speech model selection; cached models/transcripts; cooperative cancellation | Base model failed Arabic synthetic speech and made Turkish/Korean errors. Long human speech and larger-model quality not established |
| Media outputs | Real FFmpeg SRT/MKV track/MP4 burn pipeline retained; native local MP4/MKV/MP3 conversion screen added | Conversion UI not comprehensively exercised; Arabic/Korean visual glyph quality needs Windows fonts and human inspection |
| Security | Signed update trust boundary, constrained asset URLs and redirects, no shell installation; diagnostic credential/query redaction; suppressed unsolicited external logger; updated vulnerable dependency ranges | Same-user malware is not prevented. Full native binary/model/license audit incomplete |
| Website | Setup asset selection, stable latest fallback, stale download/checksum removal, four-language development status, install/privacy/changelog information | Source changes only; website not published; no new mobile browser audit |

## Confirmed issues addressed

1. `auto_update_check` existed in 1.7 settings but no updater implemented it. A signed updater now implements the behavior and fails closed without trust.
2. Original source SRT was unconditionally exported even when the user wanted only the final translation. Desktop calls now default to final-only, retain internal transcript cache, and offer explicit original export. The pipeline API retains its historical default for existing CLI callers.
3. Metadata preview failures now show the actual redacted error instead of rendering empty video information.
4. New thumbnail retrieval has a 5 MiB byte cap and runs off the Tk thread. Media updates retain card widgets rather than rebuilding each progress tick. Update progress notifications are throttled.
5. Old website fallback pinned 1.5.0 filenames and checksum. It now routes to the latest stable page if API lookup fails, recognizes the 2.x Setup name and hides an unknown checksum.
6. Dependency audit initially reported 45 vulnerability entries across selected Pillow 12.3.0 and cryptography 48.0.1. Requirements now pin Pillow 13.0.0 and cryptography 50.0.2; the repeated resolved-dependency audit reported no known vulnerabilities. An audit is a point-in-time database result, not proof that the application has no security defects.
7. The completed queue filter previously included failed/cancelled jobs, so Clear Completed could remove retryable entries. It now filters strictly Completed, and Failed has its own filter/test.
8. Supplied documentation attributed unrelated products/features and used stale names. The current catalog is grounded in actual Veyora code; old reports are explicitly historical.

## Tests actually executed

- Baseline source: **84 passed, 3 skipped** in 6.27 s under the same Linux dependency environment.
- Final Python suite: **120 passed, 3 skipped**; see `review-tests.xml` for the authoritative count. It covers real local yt-dlp downloads, range-based resume/cancel, HTTP failure handling, queue behavior, FFmpeg extraction/track/burn/cancel/progress, subtitle parsing/export preferences, models/routes, performance bounds and secure updater fixtures.
- Website Node suite: **10 passed**, including correct Setup preference and rejection of mismatched/untrusted assets.
- Updater: **27 fixture tests** including version/prerelease ordering, valid signatures, tampering, unknown key, expired manifest, wrong target/filename/hash/size/URL, redirect rejection, cancellation, truncation, offline error and old/same version. Fixtures are inert bytes; none are executed.
- Native GUI: launched under Linux Xvfb using system Tk with antialiased fonts. Navigated Downloads/History/Settings/Translation/Convert/Home; switched Arabic/English and audio/video; resized to 1080×760, 1280×820, 1536×980; saved `gui-review.png`. Visual comparison led to corrected font rendering, icon treatment, option-card reflow and horizontal download rows. Full reference fidelity is not claimed.
- Actual GUI Download button: generated an original short video with FFmpeg, served it over localhost HTTP, clicked/enqueued through the real UI handler and observed **Completed** with a real file. Evidence: `gui-download-result.json`, `gui-download-actual.png`. No example progress values or completed downloads were fabricated for the screenshot.
- All six direct translation packages were downloaded and SHA-256 verified. **12/12 real text inference routes completed**, using cached packages on reuse. Evidence: `inference-matrix-2.json`. Some outputs omit content; completion is not an accuracy pass.
- Actual speech recognition: four espeak-ng generated WAV samples were run through Whisper base. English yielded the expected sentence; Turkish/Korean yielded nonempty but inaccurate text; Arabic yielded zero cues. Three source runs proceeded through nine target translations. Evidence: `speech-matrix-2.json`. These are synthetic, short samples, not representative human speech. **Speech quality is not approved.** A separate Arabic retry with VAD disabled also returned no segments; it did not resolve the limitation.
- Dependency audit: `dependency-audit.json` reports no known vulnerabilities for the resolved requirements after upgrades.
- Python compilation completed. Historical reports bundled in the uploaded ZIP were not reused as test results.

The three skipped Python integrations require archive environment variables; they were not silently counted as passing. Separate actual inference above does not change those skip counts.

## Performance measurements (single Linux run)

Synthetic workload: 300 queued items plus 100 complete snapshots; no media, UI rendering, models or network.

| Measurement | Supplied 1.7 | Current review |
|---|---:|---:|
| Elapsed seconds | 1.389 | 1.600 |
| Python heap peak bytes | 1,347,298 | 1,347,858 |
| Maximum process RSS KiB | 41,388 | 41,296 |

The queue benchmark does **not** demonstrate a speed or memory improvement. Single-run noise and additional default settings affect this small workload; no favorable performance claim is made. Economy/balanced/high bound model CPU threads and download concurrency, but Windows CPU/RAM/leak and long-video measurements remain incomplete. Raw evidence is under `benchmarks/*-2-review.json`.

## Required work before approval

- Owner-controlled public key enrollment and offline key custody; test an actual signed newer beta installer in disposable Windows environments before enabling production updates.
- Build Setup on Windows, run installer/reinstall/uninstall and data preservation script, test 1.7-to-2.0 migration, offline/cancel/failure/power-loss recovery and concurrent processes. No Setup artifact is provided here.
- Improve speech recognition on real consented Arabic/Turkish/Korean samples and human-review all 12 directions, timing, long media and burned/embedded glyph rendering. Current synthetic failures must not be marketed as support quality certification.
- Complete full reference-image/RTL/English localization and inspect Windows DPI scaling, narrow widths, keyboard focus and screen-reader behavior. Advanced legacy controls intentionally preserve features but use their older arrangement.
- Test live Pinterest/YouTube/other representative allowed public URLs, playlists, large downloads, remote errors and prolonged CPU/RAM usage. No DRM bypass or access restriction circumvention is added.
- Validate the Linux-generated hashed dependency lock on Windows, collect full native/runtime license notices, and resolve FFmpeg/model distribution obligations and the project's source license.
- Run mobile website visual/accessibility checks and publish only after owner review.
