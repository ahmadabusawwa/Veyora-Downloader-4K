import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules
if os.name != 'nt':raise SystemExit('Build Windows artifacts on Windows x64')
root=Path(SPECPATH).parent
ffmpeg=Path(os.environ['VEYORA_FFMPEG_DIR'])
# Operator must supply redistribution notices and source offer for the exact FFmpeg build.
notice=ffmpeg/'LICENSE.txt'
if not notice.is_file():raise SystemExit('FFmpeg redistribution LICENSE.txt is required')
datas=[(str(root/'logo.png'),'.'),(str(root/'logo.ico'),'.'),(str(notice),'licenses/ffmpeg'),(str(root/'LICENSES.md'),'licenses')]
if (root/'updater'/'trusted_keys.json').is_file():
 datas.append((str(root/'updater'/'trusted_keys.json'),'updater'))
binaries=[(str(ffmpeg/(x+'.exe')),'.') for x in ('ffmpeg','ffprobe')]
hidden=['desktop_ui','ui_icons','download_sites','performance','privacy','runtime_support','review_validation','navigation_validation','local_tasks','page_controller','playlist_page','history_page','recovery_store','session_state','thumbnail_cache','media_options_ui','media_conversion','media_validation']+collect_submodules('yt_dlp')+collect_submodules('translator')+collect_submodules('updater')
for package in ('customtkinter','faster_whisper','ctranslate2','onnxruntime','av','tokenizers','sentencepiece','cryptography'):
 d,b,h=collect_all(package);datas+=d;binaries+=b;hidden+=h
a=Analysis([str(root/'main.py')],pathex=[str(root)],binaries=binaries,datas=datas,hiddenimports=hidden)
p=PYZ(a.pure)
e=EXE(p,a.scripts,[],exclude_binaries=True,name='Veyora-Pro',icon=str(root/'logo.ico'),console=False,upx=False)
coll=COLLECT(e,a.binaries,a.datas,name='Veyora-Pro',upx=False)
