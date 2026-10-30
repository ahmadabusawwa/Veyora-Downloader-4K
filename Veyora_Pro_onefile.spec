# Build on Windows x64 with Python 3.12. Output name is separate from older EXEs.
import os
import shutil
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

if os.name != 'nt':
    raise SystemExit('Windows EXE must be built on Windows, not Linux.')
root = Path(SPECPATH)
datas = [(str(root / 'logo.png'), '.')]
binaries = []
hidden = collect_submodules('yt_dlp') + collect_submodules('translator')
for package in ['customtkinter', 'faster_whisper', 'ctranslate2', 'onnxruntime', 'av', 'tokenizers', 'sentencepiece']:
    package_data, package_bins, package_hidden = collect_all(package)
    datas += package_data
    binaries += package_bins
    hidden += package_hidden
for name in ['ffmpeg', 'ffprobe']:
    path = shutil.which(name)
    if not path:
        raise SystemExit(f'{name} missing from PATH. Install a static Windows FFmpeg distribution first.')
    binaries.append((path, '.'))
a = Analysis([str(root / 'main.py')], pathex=[str(root)], binaries=binaries,
    datas=datas, hiddenimports=hidden, hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[], noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='Veyora-Pro-1.7.0-Windows-x64',
    icon=str(root / 'logo.ico'), debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False)

