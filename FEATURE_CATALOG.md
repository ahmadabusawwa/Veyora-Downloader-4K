# Veyora actual feature inventory (2.0 review)

This replaces the misleading supplied catalog about another product. The original file remains available in Git baseline e513ce9. No third-party application inspection or reverse engineering was performed in this development session.

| Feature | Code | Validation |
|---|---|---|
| HTTP(S) download and resume | main.py, download_sites.py | Real local HTTP media integration and UI-button download |
| Queue, concurrency, pause/cancel/retry | main.py | Automated state/cancel/resume tests |
| Pinterest short links and native sites | download_sites.py | Routing tests only; no live site guarantee |
| Playlists, quality/container/audio format, thumbnail | retained main.py workflows | Existing code retained; external sites/formats not comprehensively exercised |
| History/settings/cookies/folder controls | main.py | Automated storage tests, actual GUI navigation |
| Four languages, 12 text routes | translator | Real inference in all 12; language quality not certified |
| Speech recognition | translator/transcription.py | Four synthetic sources attempted; Arabic failed, Turkish/Korean inaccurate |
| SRT export/input, MKV track, MP4 burn | translator | Actual FFmpeg integration; SRT parser/export preference unit tests |
| Native reference-based shell | desktop_ui.py | Actual Linux GUI screenshots, navigation, resize and local download |
| Signed updates | updater | Inert fixtures; production key and Windows installation unverified |
| Windows installer | packaging | Build/test scripts prepared; not executed on Windows |

No stem separation, license activation, post-download arbitrary shell automation or commercial readiness is claimed.
