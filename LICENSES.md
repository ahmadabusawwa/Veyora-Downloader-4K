# Veyora Pro — third-party notice review

This is an inventory, not a substitute for shipping the complete required license texts. The previous supplied notice mentioned NexusStream and dependencies not used here. The original is preserved in Git baseline e513ce9.

Observed installed package metadata is recorded in `docs/dependency-license-metadata.json`. CustomTkinter 6.0 reports CC0 metadata; verify its bundled assets and upstream terms rather than assuming the old 1.7 notice's MIT label. yt-dlp reports Unlicense, Requests/SentencePiece Apache-2.0, faster-whisper/CTranslate2/arabic-reshaper MIT, Pillow MIT-CMU, PyAV BSD-3-Clause, cryptography Apache-2.0 OR BSD-3-Clause, and ONNX Runtime MIT. python-bidi's metadata needs license-file inspection. Python has its own PSF license. These observations are not a complete native binary dependency audit.

FFmpeg's exact binary configuration determines LGPL/GPL and codec obligations. The Windows build refuses bundling without a supplied LICENSE.txt, but that alone does not satisfy all source, notice or redistribution conditions. PyAV, CTranslate2 and ONNX runtime also bundle native components requiring review. PyInstaller and Inno Setup have their own distribution/build terms.

Whisper and Argos model weights are not included in the source deliverable. Model archives are hash-pinned by the existing adapter. Keep their README/metadata; do not infer model or training-data redistribution rights from the surrounding application license. Korean and Turkish model license review remains incomplete. See MODEL_NOTICE.md.

Synthetic WAV fixtures were generated from the project's short greeting/weather sentences using espeak-ng solely for integration tests. No third-party recordings are included. Their results do not certify real-world speech quality.

Before distribution, collect all exact version license texts/native notices and resolve the project's own source distribution license with the owner. No blanket commercial readiness claim is made.
