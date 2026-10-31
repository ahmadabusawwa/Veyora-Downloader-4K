# Veyora Pro 2.0.3 — Independent continuation and evidence ledger

Status: **development / NOT APPROVED FOR DISTRIBUTION**. Product name and version unchanged. All changes are isolated to `repair/veyora-2.0.3-post-work-quota`; original Work branch `development/veyora-2.0.3-regression-recovery`, `main`, and historical backups are untouched. Starting Work commit: `f8025b0815009c226366a4956e122ce8bc2a136a`.

## New confirmed fixes

- Native Win32 recovery MessageBox exposed only English Yes/No button text to the native child enumeration; the Arabic body could not be asserted. Recovery now uses the existing in-app `confirmation.confirm` window, with a stable Arabic label, No/Yes buttons and proper queue callback. The installed regression review checks the actual app-owned widget and clicks No. The same confirmation component was already used to close active tasks. This is a separate UI dialog fix, not a speech-quality claim.
- Windows review CI initially lacked FFmpeg, producing 12 failed media tests, three setup errors and 210 passes. FFmpeg is now installed before running the integration tests. Subsequent review at `cef372d` ran 224 passing tests with seven skipped and one Tcl/Tk runner failure; the next run at `a93e670` ran 225 passing, seven skipped and one **new incorrect test assertion** because the UI intentionally shapes Arabic for display. That assertion now compares the shaped text using `app.t`. A green run is required before acceptance.
- Source delivery is independent of installer/test success: review CI archives **complete HEAD source** and its SHA-256 as a workflow artifact; no GitHub Release is created. A green Windows installer workflow is still required before delivering a new verified Setup.

## Existing 14 issues: current evidence (not blanket passes)

| # | Evidence and current status |
|---|---|
| 1 | **BLOCKED**: exact Another Love 04:07 media + matching failing SRT are absent. Work added SRT validation and a recognition-tail diagnostic but did not reproduce the reported 02:21 cutoff. |
| 2 | **PARTIAL**: automatic speech enhancement chooses a conservative candidate; synthetic speech tests are not equivalent to real music/lyrics with human voices. |
| 3 | **PARTIAL / QUALITY DEFECT CONFIRMED**: model translates text but sometimes literally; a prior real installed synthetic test translated “save the subtitles” as “إنقاذ العنوان الفرعي”. No verified semantic-quality fix. |
| 4 | **IMPLEMENTED IN CODE / PARTIAL QA**: automatic dialogue enhancement is in shared translation pipeline, without a separate user toggle. Human-song QA outstanding. |
| 5 | **IMPLEMENTED IN CODE / PARTIAL QA**: automatic context handling is in shared pipeline and follows original timing grouping. Semantic accuracy not certified. |
| 6 | **PARTIAL**: native-safe text and dedicated controls exist, but full manual Windows RTL audit is incomplete. |
| 7 | **IMPLEMENTED / TESTED**: local translation output controls for subtitle, video, and folder are wired, with disabled states while not complete. Actual Windows result tests exist. |
| 8 | **IMPLEMENTED / TESTED**: SRT blank, malformed or nonchronological cues are rejected without replacing final output. Media-tail coverage is a separate unresolved inference problem. |
| 9 | **IMPLEMENTED / TESTED**: video conversion and MP3/WAV extraction use distinct operations and options. MOV/AVI were also added. |
| 10 | **IMPLEMENTED / TESTED WITH SYNTHETIC MEDIA**: post-download clip uses validated start/end with real FFmpeg and clip-relative subtitle times; broad websites and long real videos not exhaustively tested. |
| 11 | **IMPLEMENTED / PARTIAL END-TO-END QA**: local and downloaded workflows route through the same translation engine; real fixture shows end-to-end translation. |
| 12 | **TEXT INFERENCE DONE; MULTILINGUAL SPEECH PARTIAL**: supported configured languages are ar,en,tr,ko (12 directed text routes). Work's synthetic speech matrix: en success, ar failed to recognize any speech, tr/ko produced inaccurate transcripts. Not evidence of human speech accuracy in all languages. |
| 13 | **IMPLEMENTED / TESTED**: stale default media metadata is cleared and async previews are revision-gated. |
| 14 | **IMPLEMENTED / TESTED STATIC/NATIVE**: Arabic auto-detect selected label normalizes for Win32 menu widgets; deployed visual confirmation is still a Windows acceptance gate. |

## Additional source inspection

50 production Python modules were retrieved and scanned for literal `shell=True`, `eval(`, `exec(`, bare `except:`, TODO/FIXME placeholders, and major subprocess call sites. None matched those first five risky signatures, but **this is a limited signature audit, not a full security certification**. Reviewed source paths cover desktop/navigation, downloader, translation, transcoding, conversion/clipping, settings/history, model download, file opening, updater and packaging. The update trust store is empty by default and production signed updates require owner key enrollment; do not silently enable them. Real-site behavior, adverse network conditions, installer migration and power-loss recovery remain outside this audit.

## Acceptance gate

Do not merge PR #3, publish a Release, or call Setup production-ready until the Windows test job and full installed/portable verification pass. Upload the exact failing Another Love MP4 and SRT for issue #1. No speed optimization performed.

## Confirmed additional defect fixed: thumbnail fan-out

When two UI consumers requested the same thumbnail concurrently, `thumbnail_cache.request` coalesced callbacks but invoked them without exception isolation. A destroyed/throwing first consumer prevented the second from receiving the thumbnail; the worker also logged an uncaught exception. Each callback is now guarded and separately logged. A deterministic regression test queues two subscribers, makes the first throw, and asserts delivery to the second. This is a correctness fix; no speed optimization or new feature was introduced.

## Confirmed additional defect fixed: stale metadata after failed repeat analysis

The Dashboard's `show_preview` failure branch previously updated only the title/error line, leaving the last successful resolution, HDR/FPS, and thumbnail displayed. A repeat analysis of the same URL could also accept a previously scheduled thumbnail because the draft URL revision did not change. The failure path now clears metadata and images before presenting the error, and a monotonically increasing thumbnail generation rejects stale image callbacks even on same-URL reanalysis. A GUI regression test checks the failure reset. This does not change download or translation behavior.
