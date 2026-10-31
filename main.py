import os
import sys
import json
import threading
import queue
import time
import subprocess
import platform
import re
import shutil
import glob
import copy
import uuid
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

# Application version
APP_VERSION = "2.0.3"

LANGUAGES = {'ar': 'Arabic', 'en': 'English', 'tr': 'Turkish', 'ko': 'Korean'}
TRANSLATION_DIRECTIONS = {'auto': ('en', 'ar'), 'auto-ar': ('en', 'ar'), 'auto-en': ('ar', 'en')}
SUBTITLE_CHOICES = {f'{name} ({code})': code for code, name in LANGUAGES.items()}
# Preserve saved direction keys from previous releases.
SUBTITLE_CHOICES.update({'Auto-Translate: English -> Arabic': 'auto-ar', 'Auto-Translate: Arabic -> English': 'auto-en'})
for source, source_name in LANGUAGES.items():
    for target, target_name in LANGUAGES.items():
        if source == target or (source, target) in (('en', 'ar'), ('ar', 'en')):
            continue
        key = f'auto-{source}-{target}'
        TRANSLATION_DIRECTIONS[key] = (source, target)
        SUBTITLE_CHOICES[f'Auto-Translate: {source_name} -> {target_name}'] = key
for target in LANGUAGES:
    key = 'detect-' + target
    TRANSLATION_DIRECTIONS[key] = ('auto', target)
    SUBTITLE_CHOICES['Detect speech -> ' + LANGUAGES[target]] = key
for _code in LANGUAGES:
    TRANSLATION_DIRECTIONS['transcribe-'+_code]=(_code,_code)
AUTO_TRANSLATION_MODES = tuple(TRANSLATION_DIRECTIONS)


def selected_subtitle_language(display):
    if display in ('Auto-Translate to Arabic', 'auto-en-ar'):
        return 'auto-ar'  # legacy label / explicit alias
    if display in ('Auto-Translate to English', 'auto-ar-en'):
        return 'auto-en'
    if display in SUBTITLE_CHOICES:
        return SUBTITLE_CHOICES[display]
    if display in TRANSLATION_DIRECTIONS or display in LANGUAGES:
        return display
    raise ValueError('Select a supported subtitle language or translation direction')


# Ensure dependencies are available or gracefully handled
try:
    import customtkinter as ctk
    from PIL import Image, ImageTk
    from tkinter import filedialog, Menu, messagebox
except ImportError:
    print("Error: customtkinter and pillow are required. Run: pip install -r requirements.txt")
    sys.exit(1)

try:
    import yt_dlp
except ImportError:
    print("Error: yt-dlp is required. Run: pip install -r requirements.txt")
    sys.exit(1)

# Try importing Arabic text reshaping libraries (optional)
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    HAS_ARABIC_LIBS = True
except ImportError:
    HAS_ARABIC_LIBS = False

# --- CONFIGURATION & STORAGE ---
CONFIG_DIR = Path(os.environ.get("VEYORA_CONFIG_DIR", str(Path.home() / ".veyora")))
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = CONFIG_DIR / "settings.json"
HISTORY_FILE = CONFIG_DIR / "history.json"
CONFIG_FILE = CONFIG_DIR / "config.json"
MODELS_DIR = CONFIG_DIR / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR = CONFIG_DIR / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS = {
    "download_dir": str(Path.home() / "Downloads" / "Veyora"),
    "max_concurrent": 3,
    "quality": "Best Available (4K/HD)",
    "format": "MP4",
    "extract_audio": False,
    "audio_format": "MP3",
    "audio_bitrate": "320 kbps",
    "download_subs": True,
    "sub_lang": "auto-ar",
    "subtitle_mode": "separate",
    "save_thumbnail": True,
    "smart_mode": False,
    "speed_limit": 0,
    "theme": "Dark",
    "proxy": "",
    "cookies_file": "",
    "auto_update_check": True,
    "allow_prereleases": False,
    "save_original_subtitles": False,
    "ui_language": "ar",
    "performance_mode": "balanced",
    "speech_model": "base",
    "save_description": False,
    "auto_split_clips": False,
    "clip_enabled": False,
    "clip_start": "00:00:00",
    "clip_end": "00:12:34",
}

def atomic_json_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(data):
    try:
        atomic_json_write(CONFIG_FILE, data)
    except Exception as e:
        print("Failed to save config:", e)

# --- ARABIC TEXT SUPPORT ---
def fix_arabic_text(text):
    if not text:
        return text
    try:
        if HAS_ARABIC_LIBS:
            reshaped = arabic_reshaper.reshape(text)
            display = get_display(reshaped)
            return display
        else:
            for ext in ['.mp4', '.mkv', '.mov', '.webm', '.mp3', '.m4a', '.srt', '.vtt', '.avi', '.flv']:
                text = text.replace(ext, '')
            return text
    except Exception:
        return text

ARABIC_FONT = ("Segoe UI", 13, "bold")
ARABIC_FONT_SMALL = ("Segoe UI", 11)
ARABIC_FONT_TITLE = ("Segoe UI", 14, "bold")

# Site support uses native yt-dlp extractors plus Pinterest short-link routing.
from download_sites import (SUPPORTED_PLATFORMS, POPULAR_SITES, detect_platform, is_valid_url,
    normalize_url, create_downloader, metadata_options, entry_page_url, friendly_download_error)

# --- SETTINGS MANAGER ---
class SettingsManager:
    _lock = threading.RLock()
    @staticmethod
    def load():
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return {**DEFAULT_SETTINGS, **data}
            except Exception:
                pass
        return DEFAULT_SETTINGS.copy()

    @staticmethod
    def save(settings):
        try:
            with SettingsManager._lock:
                atomic_json_write(SETTINGS_FILE, settings)
        except Exception as e:
            print("Failed to save settings:", e)


# --- HISTORY MANAGER ---
class HistoryManager:
    _lock = threading.Lock()
    @staticmethod
    def load():
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, list) else []
            except Exception:
                pass
        return []

    @staticmethod
    def add(item):
        with HistoryManager._lock:
            history = HistoryManager.load()
            history.insert(0, item)
            atomic_json_write(HISTORY_FILE, history[:1000])


# --- FILE UTILITIES ---
def open_file_in_explorer(file_path):
    if not os.path.exists(file_path):
        return False
    try:
        if platform.system() == "Windows":
            subprocess.run(['explorer', '/select,', os.path.normpath(file_path)], check=True)
        elif platform.system() == "Darwin":
            subprocess.run(['open', '-R', os.path.normpath(file_path)], check=True)
        else:
            subprocess.run(['xdg-open', os.path.dirname(os.path.normpath(file_path))], check=True)
        return True
    except Exception as e:
        print(f"Failed to open file in explorer: {e}")
        return False

def open_folder_in_explorer(folder_path):
    if not os.path.exists(folder_path):
        return False
    try:
        if platform.system() == "Windows":
            os.startfile(folder_path)
        elif platform.system() == "Darwin":
            subprocess.run(['open', os.path.normpath(folder_path)], check=True)
        else:
            subprocess.run(['xdg-open', os.path.normpath(folder_path)], check=True)
        return True
    except Exception as e:
        print(f"Failed to open folder in explorer: {e}")
        return False

def check_ffmpeg():
    try:
        from translator.video_renderer import executable
        subprocess.run([executable('ffmpeg'), '-version'], capture_output=True, check=True, timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return True
    except Exception:
        return False

def check_ffprobe():
    try:
        from translator.video_renderer import executable
        subprocess.run([executable('ffprobe'), '-version'], capture_output=True, check=True, timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return True
    except Exception:
        return False

MEDIA_EXTENSIONS = {'.mp4', '.mkv', '.mov', '.webm', '.mp3', '.m4a', '.avi', '.flv', '.wav', '.ogg', '.opus'}
SUBTITLE_EXTENSIONS = {'.srt', '.vtt', '.ass', '.ssa', '.sub', '.sbv'}

# --- DOWNLOAD ENGINE ---
class DownloadEngine:
    @staticmethod
    def fetch_metadata(url, cookies_file="", playlist=False):
        try:
            url = normalize_url(url)
        except ValueError as exc:
            return {'error': str(exc)}
        ydl_opts = metadata_options(url, cookies_file)
        if playlist:
            ydl_opts["noplaylist"] = False
        platform = detect_platform(url)

        try:
            with create_downloader(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return None

                if 'entries' in info:
                    entries = []
                    for entry in info['entries']:
                        if entry:
                            entries.append({
                                'id': entry.get('id', ''),
                                'title': entry.get('title', 'Unknown'),
                                'duration': entry.get('duration', 0),
                                'url': entry_page_url(entry, platform),
                                'thumbnail': entry.get('thumbnail', ''),
                            })
                    return {
                        'type': 'playlist',
                        'title': info.get('title') or info.get('id') or 'Playlist',
                        'uploader': info.get('uploader', 'Unknown'),
                        'count': len(entries),
                        'entries': entries,
                        'platform': platform,
                    }
                else:
                    formats = info.get('formats', [])
                    qualities = set()
                    audio_formats = []
                    for f in formats:
                        height = f.get('height')
                        if height:
                            qualities.add(f"{height}p")
                        acodec = f.get('acodec', 'none')
                        vcodec = f.get('vcodec', 'none')
                        if acodec != 'none' and vcodec == 'none':
                            audio_formats.append({
                                'format_id': f.get('format_id', ''),
                                'ext': f.get('ext', ''),
                                'abr': f.get('abr') or 0,
                                'filesize': f.get('filesize') or f.get('filesize_approx', 0),
                                'acodec': acodec,
                            })
                    if info.get('resolution'):
                        qualities.add(info.get('resolution'))

                    seen_audio = set()
                    unique_audio = []
                    for af in audio_formats:
                        key = (af['ext'], round(af['abr'] or 0))
                        if key not in seen_audio:
                            seen_audio.add(key)
                            unique_audio.append(af)
                    unique_audio.sort(key=lambda x: x['abr'], reverse=True)

                    video_title = info.get('title', 'Unknown Title')
                    filesize = info.get('filesize') or info.get('filesize_approx', 0)
                    video_id = info.get('id', '')

                    return {
                        'type': 'video',
                        'title': video_title,
                        'id': video_id,
                        'duration': info.get('duration', 0),
                        'thumbnail': info.get('thumbnail', ''),
                        'uploader': info.get('uploader', 'Unknown'),
                        'view_count': info.get('view_count', 0),
                        'qualities': sorted(qualities, key=lambda x: int(x.replace('p', '')) if x.replace('p', '').isdigit() else 0, reverse=True),
                        'filesize': filesize,
                        'formats': formats,
                        'audio_formats': unique_audio,
                        'subtitles': info.get('subtitles', {}),
                        'automatic_captions': info.get('automatic_captions', {}),
                        'platform': info.get('extractor_key', platform),
                    }
        except Exception as exc:
            from runtime_support import friendly_error
            return {'error': friendly_error(exc)}

    @staticmethod
    def get_format_string(settings):
        extract_audio = settings.get('extract_audio', False)
        if extract_audio:
            return 'bestaudio/best'

        quality = settings.get('quality', 'Best Available (4K/HD)')
        if quality=='Best Available':
            return 'bestvideo+bestaudio/best'
        if settings.get('strict_quality'):
            height=next((n for n in ('2160','1080','720','480') if n in quality),None)
            if height:
                return f'bestvideo[height<=?{height}]+bestaudio/best[height<=?{height}]'
        if '4K' in quality or '2160' in quality or 'Best' in quality:
            return 'bestvideo[height<=2160]+bestaudio/best[height<=2160]/best'
        elif '1440' in quality:
            return 'bestvideo[height<=1440]+bestaudio/best[height<=1440]/best'
        elif '1080' in quality:
            return 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best'
        elif '720' in quality:
            return 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'
        elif '480' in quality:
            return 'bestvideo[height<=480]+bestaudio/best[height<=480]/best'
        else:
            return 'bestvideo+bestaudio/best'

    @staticmethod
    def build_ydl_opts(task_item, progress_callback, selected_folder):
        settings = task_item['settings']
        url = normalize_url(task_item['url'])
        out_dir = Path(selected_folder)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Never interpolate remote IDs into an output template.
        outtmpl = str(out_dir / '%(title).80s [%(id)s].%(ext)s')

        ydl_opts = {
            'outtmpl': outtmpl,
            'progress_hooks': [lambda d: progress_callback(task_item['id'], d)],
            'quiet': True,
            'no_warnings': True,
            'concurrent_fragment_downloads': __import__('performance').profile()[2],
            'buffersize': 1024 * 64,
            'noresizebuffer': True,
            'noprogress': True,
            # Preserve byte ranges supplied by HLS manifests; forced HTTP chunks corrupt them.
            'skip_unavailable_fragments': False,
            'nocheckcertificate': False,
            'windowsfilenames': True,
            'restrictfilenames': False,
            'encoding': 'utf-8',
            'ignoreerrors': False,
            'retries': 10,
            'fragment_retries': 10,
            'socket_timeout': 30,
        }

        from translator.video_renderer import executable
        try:
            ydl_opts['ffmpeg_location'] = str(Path(executable('ffmpeg')).parent)
        except Exception:
            pass  # yt-dlp reports any required missing postprocessor.
        platform = detect_platform(url)

        extract_audio = settings.get('extract_audio', False)
        audio_format_id = settings.get('audio_format_id', '')
        if extract_audio and audio_format_id:
            ydl_opts['format'] = audio_format_id
        else:
            ydl_opts['format'] = DownloadEngine.get_format_string(settings)

        if extract_audio:
            audio_format = settings.get('audio_format', 'mp3').lower()
            audio_bitrate = settings.get('audio_bitrate', '320k').replace(' kbps', 'k')
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': audio_format,
                'preferredquality': audio_bitrate.rstrip('k'),
            }]
            if settings.get('save_thumbnail', True):
                if 'postprocessors' not in ydl_opts:
                    ydl_opts['postprocessors'] = []
                ydl_opts['postprocessors'].append({'key': 'EmbedThumbnail'})
                ydl_opts['writethumbnail'] = True
        else:
            fmt = settings.get('format', 'MP4').lower()
            ydl_opts['merge_output_format'] = ('mkv' if settings.get('download_subs') and settings.get('subtitle_mode') in ('embed', 'both') and settings.get('sub_lang') not in AUTO_TRANSLATION_MODES else fmt)
            if settings.get('save_thumbnail', True):
                ydl_opts['writethumbnail'] = True

        auto_translate = settings.get('sub_lang') in AUTO_TRANSLATION_MODES
        subtitles = bool(settings.get('download_subs', True)) and not extract_audio
        # AI translation has its own pipeline after the final media path is known.
        ydl_opts.update({
            'noplaylist': True, 'continuedl': True, 'nopart': False,
            'overwrites': False,
            'subtitleslangs': [settings.get('sub_lang', 'ar')],
            'writesubtitles': subtitles and not auto_translate,
            'writeautomaticsub': subtitles and not auto_translate,
            'subtitlesformat': 'srt/vtt/best',
        })
        ydl_opts.setdefault('postprocessors', [])
        if settings.get('force_container') and not extract_audio:
            ydl_opts['postprocessors'].append({'key':'FFmpegVideoRemuxer','preferedformat':settings.get('format','MP4').lower()})
        if subtitles and not auto_translate:
            ydl_opts['postprocessors'].append({'key': 'FFmpegSubtitlesConvertor', 'format': 'srt'})
            if settings.get('subtitle_mode') in ('embed', 'both'):
                ydl_opts['postprocessors'].append({'key': 'FFmpegEmbedSubtitle', 'already_have_subtitle': True})

        if settings.get('proxy'):
            ydl_opts['proxy'] = settings['proxy']

        speed_limit = settings.get('speed_limit', 0)
        if speed_limit > 0:
            ydl_opts['ratelimit'] = speed_limit * 1024

        if settings.get('save_description', False):
            ydl_opts['writedescription'] = True

        cookies_file = settings.get('cookies_file', '')
        if cookies_file and os.path.exists(cookies_file):
            ydl_opts['cookiefile'] = cookies_file

        return ydl_opts, out_dir

    @staticmethod
    def download_task(task_item, progress_callback, completion_callback, pause_event, cancel_event, selected_folder):
        url = task_item['url']
        settings = task_item['settings']

        try:
            if settings.get('clip_enabled'):
                from media_clipping import clip_interval
                clip_interval(settings.get('clip_start',''),settings.get('clip_end',''))
                if settings.get('extract_audio'):
                    raise ValueError('Video clipping is unavailable for audio-only downloads')
            url = normalize_url(url)
            selected_folder = selected_folder or settings['download_dir']
            ydl_opts, out_dir = DownloadEngine.build_ydl_opts(task_item, progress_callback, selected_folder)
            task_item['out_dir'] = out_dir
            last_update = [0.0]

            def checkpoint():
                if cancel_event.is_set():
                    raise RuntimeError("Cancelled by user")
                while pause_event.is_set():
                    if cancel_event.wait(0.1):
                        raise RuntimeError("Cancelled by user")

            def hook(data):
                checkpoint()
                now = time.monotonic()
                if data.get('status') != 'downloading' or now - last_update[0] >= 0.2:
                    last_update[0] = now
                    progress_callback(task_item['id'], data)

            ydl_opts['progress_hooks'] = [hook]
            def postprocessor_hook(data):
                checkpoint()
                progress_callback(task_item['id'], {'status': 'finished'})
            ydl_opts['postprocessor_hooks'] = [postprocessor_hook]
            final_paths = []
            def final_hook(filename):
                checkpoint()
                final_paths.append(str(filename))
            ydl_opts['post_hooks'] = [final_hook]
            checkpoint()
            with create_downloader(ydl_opts) as ydl:
                result = ydl.extract_info(url, download=True)
            checkpoint()
            # Use yt-dlp's final path, never guess from unrelated files in the folder.
            candidates = final_paths + ([result.get('filepath')] if result else [])
            final_path = next((Path(f) for f in candidates if f and Path(f).is_file()), None)
            if final_path is None:
                raise RuntimeError("The downloader did not return an existing final media file")
            if settings.get('clip_enabled'):
                from media_clipping import clip_media,clip_interval,clip_subtitles
                progress_callback(task_item['id'],{'status':'translation','stage':'Full download finished; clipping selected interval locally','fraction':None})
                original=final_path
                final_path=clip_media(original,out_dir,settings['clip_start'],settings['clip_end'],checkpoint,
                    progress=lambda fraction,eta,speed:progress_callback(task_item['id'],{'status':'translation','stage':'Clipping downloaded video','fraction':fraction}))
                task_item['original_downloaded_file']=str(original)
                # Existing site captions use the full-video timeline. Shift them
                # before burning; generated speech captions instead use the clip.
                if settings.get('download_subs') and settings.get('sub_lang') not in AUTO_TRANSLATION_MODES:
                    start,end=clip_interval(settings['clip_start'],settings['clip_end'])
                    for value in ((result or {}).get('requested_subtitles') or {}).values():
                        if value.get('filepath'):
                            full=Path(value['filepath']).with_suffix('.srt')
                            target=final_path.with_suffix('.srt')
                            clip_subtitles(full,start,end,target)
                            value['filepath']=str(target)
                            task_item['subtitle_file']=str(target)
                            if settings.get('subtitle_mode') in ('embed','both'):
                                from translator.video_renderer import embed_subtitles
                                embedded=final_path.with_name(final_path.stem+'.subtitled'+final_path.suffix)
                                embed_subtitles(final_path,target,embedded,checkpoint,subtitle_lang=settings.get('sub_lang','ar'))
                                final_path=embedded
            task_item['downloaded_file'] = str(final_path)
            task_item['title'] = (result or {}).get('title') or final_path.stem
            if (settings.get('download_subs') and not settings.get('extract_audio')
                    and settings.get('sub_lang') in AUTO_TRANSLATION_MODES):
                from translator.worker import run_translation
                from translator.recognition_policy import configured_translation_options
                progress_callback(task_item['id'], {'status': 'translation', 'stage': 'Preparing selected translation direction'})
                outputs = run_translation(final_path, out_dir,
                    mode=settings.get('subtitle_mode', 'separate'), checkpoint=checkpoint,
                    source_lang=TRANSLATION_DIRECTIONS[settings['sub_lang']][0],
                    target_lang=TRANSLATION_DIRECTIONS[settings['sub_lang']][1],
                    output_container=settings.get('format','MKV').lower(),
                    save_original=settings.get('save_original_subtitles', False),
                    subtitle_style=settings.get('subtitle_style'),
                    **configured_translation_options(settings),
                    progress=lambda stage, fraction=None: progress_callback(task_item['id'],
                        {'status': 'translation', 'stage': stage, 'fraction': fraction}))
                task_item['subtitle_file'] = outputs['subtitle']
                if outputs.get('coverage_report'):task_item['coverage_report']=outputs['coverage_report']
                if outputs.get('video'):
                    task_item['downloaded_file'] = outputs['video']
                    task_item['translated_video'] = True
            elif (settings.get('download_subs') and not settings.get('extract_audio')
                    and settings.get('subtitle_mode') == 'burn'):
                from translator.video_renderer import burn_subtitles
                requested = (result or {}).get('requested_subtitles') or {}
                candidates = [Path(v['filepath']).with_suffix('.srt') for v in requested.values() if v.get('filepath')]
                subtitle = next((f for f in candidates if f.is_file()), None)
                if subtitle is None:
                    raise RuntimeError('No subtitle in the selected language is available to burn')
                output = out_dir / (final_path.stem + '.burn.' + uuid.uuid4().hex[:12] + '.mp4')
                def native_burn_progress(fraction, eta, speed):
                    text = 'Burning downloaded subtitles'
                    if fraction is not None:
                        text += f': {fraction*100:.1f}%'
                    if speed is not None:
                        text += f' | {speed:.2f}x'
                    if eta is not None:
                        text += f' | ETA ~{int(eta)//60}:{int(eta)%60:02d}'
                    else:
                        text += ' | ETA estimating'
                    progress_callback(task_item['id'], {'status': 'translation', 'stage': text, 'fraction': fraction})
                burn_subtitles(final_path, subtitle, output, checkpoint, progress=native_burn_progress, **({'style':settings['subtitle_style']} if settings.get('subtitle_style') else {}))
                task_item['downloaded_file'] = str(output)
            checkpoint()
            progress_callback(task_item['id'],{'status':'finished','stage':'Checking final media file'})
            from translator.video_renderer import get_ffprobe_info
            final=Path(task_item['downloaded_file'])
            if not final.is_file() or final.stat().st_size<=0 or not get_ffprobe_info(final).get('streams'):
                raise RuntimeError('Final media output validation failed')
            checkpoint()
            if settings.get('auto_split_clips') and not settings.get('extract_audio'):
                from media_clipping import split_long_video
                task_item['split_files']=split_long_video(final,out_dir,checkpoint,
                    progress=lambda stage,fraction:progress_callback(task_item['id'],dict(status='translation',stage=stage,fraction=fraction)),
                    subtitle=task_item.get('subtitle_file'),subtitle_mode=settings.get('subtitle_mode','separate'),
                    language=TRANSLATION_DIRECTIONS.get(settings.get('sub_lang'),('en',settings.get('sub_lang','ar')))[1])
            completion_callback(task_item['id'], True, "Download completed successfully.")
        except Exception as exc:
            from runtime_support import friendly_error,log_failure
            if not cancel_event.is_set():log_failure(exc,'download task '+task_item['id'])
            completion_callback(task_item['id'], False,
                friendly_error(exc, settings.get('ui_language') == 'ar', cancel_event.is_set(),record=False))


def cleanup_leftover_files(directory, title_pattern):
    """Avoid deleting unrelated files in a shared download directory.

    yt-dlp can leave resumable .part files. Preserve these for retries;
    targeted cleanup should use exact paths recorded by the download engine.
    """
    return


# --- DOWNLOAD QUEUE MANAGER ---
class DownloadQueueManager:
    TERMINAL = ('Completed', 'Failed', 'Cancelled')

    def __init__(self, update_ui_callback, max_concurrent=3):
        self.tasks, self.futures = {}, {}
        self.task_order = []
        self.max_concurrent = max(1, min(5, int(max_concurrent)))
        self.update_ui_callback = update_ui_callback
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.pause_events, self.cancel_events = {}, {}
        self.ui_dirty = threading.Event()
        self.closed = False
        from recovery_store import RecoveryStore, recovery_path
        self.recovery = RecoveryStore(recovery_path(CONFIG_DIR))
        self.recoverable = self.recovery.load()
        # Terminal outputs must be visible after restart even when no resume prompt is needed.
        for saved in list(self.recoverable):
            if saved.get('status') in self.TERMINAL and saved.get('id'):
                tid=saved['id'];self.tasks[tid]=saved;self.task_order.append(tid)
                self.pause_events[tid],self.cancel_events[tid]=threading.Event(),threading.Event()
        self.recoverable=[t for t in self.recoverable if t.get('id') not in self.tasks]

    def _journal(self):
        if self.closed:
            return self.recovery.generation
        with self.lock:
            return self.recovery.submit([t for t in self.recoverable if t.get('id') not in self.tasks] + [self.tasks[tid] for tid in self.task_order])

    def register_local_result(self,task,settings):
        if task.status!='completed' or not task.result:return
        with self.lock:
            if task.id in self.tasks:return
            result=task.result;path=result.get('video') or result.get('subtitle')
            if not path:return
            self.tasks[task.id]=dict(id=task.id,url='',settings=copy.deepcopy(settings),title=Path(task.path).name,
                progress=1.0,speed='',eta='',status='Completed',error=None,downloaded_file=path,
                subtitle_file=result.get('subtitle'),translated_video=bool(result.get('video')),
                selected_folder=str(Path(path).parent),platform='Local media',show_folder_available=True,filesize=0,
                local_result=True)
            self.task_order.append(task.id)
            self.pause_events[task.id],self.cancel_events[task.id]=threading.Event(),threading.Event()
        self._journal();self._notify_ui()

    def restore_previous(self):
        """Explicit consent only; retain IDs, output template and partial files."""
        with self.lock:
            for saved in self.recoverable:
                if saved.get('id') in self.tasks:
                    continue
                if not is_valid_url(saved.get('url', '')):
                    continue
                tid = saved['id']
                if saved.get('status') not in self.TERMINAL:
                    saved.update(status='Queued', error=None)
                self.tasks[tid] = saved
                self.task_order.append(tid)
                self.pause_events[tid], self.cancel_events[tid] = threading.Event(), threading.Event()
            self.recoverable = []
        self._journal()
        self._notify_ui()
        self._process_queue()

    def _notify_ui(self):
        # Worker threads never call Tk, including Tk.after().
        self.ui_dirty.set()

    def poll_ui(self):
        if self.ui_dirty.is_set():
            self.ui_dirty.clear()
            self.update_ui_callback()

    def add_task(self, url, settings, title="Resolving...", selected_folder=None, video_id="", thumbnail=""):
        if not is_valid_url(url):
            raise ValueError("Only valid HTTP(S) URLs are supported")
        url = normalize_url(url)
        tid = uuid.uuid4().hex
        with self.lock:
            for existing in self.tasks.values():
                if existing['url'] == url and existing['settings'] == settings and existing['status'] not in self.TERMINAL:
                    return existing['id']
            if self.closed:
                raise RuntimeError("Application is closing")
            self.tasks[tid] = dict(id=tid, url=url, settings=copy.deepcopy(settings), title=title,
                progress=0.0, speed='0 KB/s', eta='Calculating...', status='Queued', error=None,
                downloaded_file=None, show_folder_available=False, filesize=0, format_badge='',
                selected_folder=selected_folder or settings['download_dir'],
                platform=detect_platform(url), video_id=video_id, thumbnail=thumbnail)
            self.task_order.append(tid)
            self.pause_events[tid], self.cancel_events[tid] = threading.Event(), threading.Event()
        self._journal()
        self._notify_ui()
        self._process_queue()
        return tid

    def _process_queue(self):
        with self.lock:
            if self.closed:
                return
            for tid in self.task_order:
                if len(self.futures) >= self.max_concurrent:
                    break
                if self.tasks[tid]['status'] != 'Queued' or tid in self.futures:
                    continue
                self.tasks[tid]['status'] = 'Downloading'
                future = self.executor.submit(self._run_task, tid)
                self.futures[tid] = future
                future.add_done_callback(lambda f, task_id=tid: self._task_done(task_id, f))
        self._notify_ui()

    def _task_done(self, tid, future):
        with self.lock:
            task = self.tasks.get(tid)
            if task and task['status'] not in self.TERMINAL:
                error = future.exception() if not future.cancelled() else None
                task.update(status='Failed', error=str(error or 'Worker exited without completion'))
            self.futures.pop(tid, None)
        self._journal()
        self._notify_ui()
        self._process_queue()

    def _run_task(self, tid):
        self.recovery.flush()  # worker: durable intent before network transfer
        task = self.tasks[tid]
        def progress_cb(task_id, data):
            with self.lock:
                t = self.tasks.get(task_id)
                if not t or self.cancel_events[task_id].is_set():
                    return
                details = data.get('info_dict') or {}
                if details.get('thumbnail'):
                    t['thumbnail'] = details['thumbnail']
                state = data.get('status')
                if state == 'downloading':
                    # yt-dlp can run metadata/pre-process hooks before the media
                    # transfer. The latest actual byte event owns this state.
                    t['status'] = 'Downloading'
                    total = data.get('total_bytes') or data.get('total_bytes_estimate') or 0
                    if total:
                        t['filesize'] = total
                        t['progress'] = min(1.0, max(0.0, data.get('downloaded_bytes', 0) / total))
                    t['speed'] = f"{(data.get('speed') or 0) / 1048576:.2f} MB/s"
                    eta = data.get('eta')
                    t['eta'] = f"{int(eta)//60}:{int(eta)%60:02d}" if eta is not None else 'Calculating...'
                elif state in ('finished', 'translation'):
                    if data.get('stage'):t['stage']=data['stage']
                    t['status'] = 'Translating' if state == 'translation' else 'Processing / Muxing'
                    if state == 'translation':
                        t['stage'] = data.get('stage', '')
                        t['progress'] = min(1.0, max(0.0, data.get('fraction') or 0))
                if self.pause_events[task_id].is_set():
                    t['status'] = 'Paused'
            self._notify_ui()

        def completion_cb(task_id, success, message):
            history = None
            with self.lock:
                t = self.tasks[task_id]
                if self.cancel_events[task_id].is_set():
                    t['status'] = 'Cancelled'
                elif success:
                    f = Path(t['downloaded_file'])
                    if not f.is_file() or f.stat().st_size<=0:
                        raise RuntimeError('Final download output is missing or empty')
                    size = f.stat().st_size
                    t.update(status='Completed', progress=1.0, filesize=size, show_folder_available=True)
                    history = dict(title=t['title'], url=t['url'],
                        time=time.strftime('%Y-%m-%d %H:%M:%S'), status='Success',
                        file_path=str(f), platform=t['platform'])
                else:
                    t.update(status='Failed', error=message)
            if history:
                HistoryManager.add(history)
            self._journal()
            self._notify_ui()

        DownloadEngine.download_task(task, progress_cb, completion_cb,
            self.pause_events[tid], self.cancel_events[tid], task['selected_folder'])

    def pause_task(self, tid):
        with self.lock:
            t = self.tasks.get(tid)
            if t and t['status'] in ('Queued', 'Downloading'):
                self.pause_events[tid].set()
                t['status'] = 'Paused'
        self._notify_ui()

    def resume_task(self, tid):
        with self.lock:
            t = self.tasks.get(tid)
            if t and t['status'] == 'Paused':
                self.pause_events[tid].clear()
                t['status'] = 'Downloading' if tid in self.futures else 'Queued'
        self._notify_ui()
        self._process_queue()

    def cancel_task(self, tid):
        with self.lock:
            t = self.tasks.get(tid)
            if t and t['status'] not in self.TERMINAL:
                self.cancel_events[tid].set()
                self.pause_events[tid].clear()
                t['status'] = 'Cancelling' if tid in self.futures else 'Cancelled'
        self._notify_ui()
        self._process_queue()

    def retry_task(self, tid):
        with self.lock:
            t = self.tasks.get(tid)
            if t and t['status'] in ('Failed', 'Cancelled') and tid not in self.futures:
                self.pause_events[tid].clear()
                self.cancel_events[tid].clear()
                t.update(status='Queued', error=None, progress=0.0)
        self._notify_ui()
        self._process_queue()

    def remove_task(self, tid):
        with self.lock:
            if tid in self.futures or self.tasks.get(tid, {}).get('status') not in self.TERMINAL:
                return
            self.tasks.pop(tid, None)
            self.task_order.remove(tid)
            self.pause_events.pop(tid, None)
            self.cancel_events.pop(tid, None)
        self._journal()
        self._notify_ui()

    def set_max_concurrent(self, value):
        with self.lock:
            self.max_concurrent = max(1, min(5, int(value)))
        self._process_queue()

    def get_tasks_by_status(self, status_filter=None):
        with self.lock:
            tasks = [copy.deepcopy(self.tasks[tid]) for tid in self.task_order]
        if status_filter == 'downloading':
            return [t for t in tasks if t['status'] not in self.TERMINAL]
        if status_filter == 'completed':
            return [t for t in tasks if t['status'] == 'Completed']
        if status_filter == 'failed':
            return [t for t in tasks if t['status'] == 'Failed']
        if status_filter == 'cancelled':
            return [t for t in tasks if t['status'] == 'Cancelled']
        return tasks

    def shutdown(self):
        self._journal()
        with self.lock:
            self.closed = True
            for tid in self.tasks:
                self.cancel_events[tid].set()
                self.pause_events[tid].clear()
        self.recovery.close()
        self.executor.shutdown(wait=False, cancel_futures=True)


# --- MAIN APPLICATION GUI ---
class VeyoraApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"Veyora Pro {APP_VERSION} - Local English-Arabic Translation")
        self.geometry("1200x800")
        self.minsize(1000, 600)

        self.settings = SettingsManager.load()
        ctk.set_appearance_mode(self.settings.get("theme", "Dark"))
        ctk.set_default_color_theme("blue")

        config = load_config()
        self.selected_folder = config.get("download_folder", self.settings.get("download_dir", str(Path.home() / "Downloads" / "Veyora")))
        Path(self.selected_folder).mkdir(parents=True, exist_ok=True)

        self.queue_manager = DownloadQueueManager(self.refresh_ui, self.settings.get("max_concurrent", 3))
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._ui_callbacks = queue.Queue()
        self._worker_poll_id = self.after(100, self._poll_workers)

        self.active_filter = "all"
        self.smart_mode = self.settings.get("smart_mode", False)
        self.playlist_data = None
        self.playlist_window = None
        self.card_widgets = {}
        self._card_buttons = {}
        self._card_snapshots = {}
        self.available_audio_formats = []
        self.audio_format_window = None

        self._card_progress_bars = {}
        self._card_info_labels = {}
        self._card_title_labels = {}

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.setup_sidebar()
        self.setup_main_content()

        self.active_tab = "Dashboard"
        self.show_tab("Dashboard")

        # CRITICAL: Bind shortcuts AFTER url_entry is created
        self._bind_language_independent_shortcuts()
        from updater.ui import UpdateUI
        self.updater = UpdateUI(self, APP_VERSION, CONFIG_DIR)
        if self.settings.get("auto_update_check", True):
            self.after(1800, lambda: self.updater.check(False))

    def _poll_workers(self):
        if getattr(self, "_closing", False):
            return
        self.queue_manager.poll_ui()
        if hasattr(self, "_refresh_local_tasks"):
            self._refresh_local_tasks()
        deadline = time.monotonic() + .008
        for _ in range(50):
            if time.monotonic() >= deadline:
                break
            try:
                callback = self._ui_callbacks.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception as exc:
                from runtime_support import friendly_error
                messagebox.showerror('Veyora', friendly_error(exc, self.settings.get('ui_language') == 'ar'))
        if not getattr(self,"_closing",False):
            self._worker_poll_id = self.after(100, self._poll_workers)

    def _on_close(self):
        self._closing = True
        if getattr(self, "_worker_poll_id", None):
            self.after_cancel(self._worker_poll_id)
        self.queue_manager.shutdown()
        self.destroy()

    def _bind_language_independent_shortcuts(self):
        """Bind keyboard shortcuts globally using physical keycodes."""
        if not hasattr(self, 'url_entry') or self.url_entry is None:
            return

        self.bind_all("<Key>", self.handle_global_shortcuts, add="+")

    def handle_global_shortcuts(self, event):
        """Handle keyboard shortcuts globally - language-independent via keycode."""
        ctrl_pressed = (event.state & 0x4) != 0 or (event.state & 0x8) != 0

        if not ctrl_pressed:
            return

        focused = self.focus_get()
        is_text_widget = False
        if focused is not None:
            widget_class = str(type(focused))
            if 'Entry' in widget_class or 'Text' in widget_class or 'entry' in widget_class.lower():
                is_text_widget = True
            if hasattr(focused, '_entry'):
                is_text_widget = True

        if not is_text_widget:
            return

        if event.keycode == 65:  # VK_A - Select All
            try:
                focused.select_range(0, 'end')
                focused.icursor('end')
            except Exception:
                try:
                    focused._entry.select_range(0, 'end')
                    focused._entry.icursor('end')
                except Exception:
                    pass
            return "break"
        elif event.keycode == 67:  # VK_C - Copy
            try:
                selected = focused.selection_get()
                self.clipboard_clear()
                self.clipboard_append(selected)
            except Exception:
                try:
                    selected = focused._entry.selection_get()
                    self.clipboard_clear()
                    self.clipboard_append(selected)
                except Exception:
                    pass
            return "break"
        elif event.keycode == 86:  # VK_V - Paste
            try:
                clipboard_text = self.clipboard_get()
                try:
                    start = focused.index("sel.first")
                    end = focused.index("sel.last")
                    focused.delete(start, end)
                except Exception:
                    pass
                cursor_pos = focused.index("insert")
                focused.insert(cursor_pos, clipboard_text)
            except Exception as e:
                try:
                    clipboard_text = self.clipboard_get()
                    try:
                        start = focused._entry.index("sel.first")
                        end = focused._entry.index("sel.last")
                        focused._entry.delete(start, end)
                    except Exception:
                        pass
                    cursor_pos = focused._entry.index("insert")
                    focused._entry.insert(cursor_pos, clipboard_text)
                except Exception as e2:
                    print(f"Paste error: {e2}")
            return "break"
        elif event.keycode == 88:  # VK_X - Cut
            try:
                selected = focused.selection_get()
                self.clipboard_clear()
                self.clipboard_append(selected)
                try:
                    start = focused.index("sel.first")
                    end = focused.index("sel.last")
                    focused.delete(start, end)
                except Exception:
                    pass
            except Exception:
                try:
                    selected = focused._entry.selection_get()
                    self.clipboard_clear()
                    self.clipboard_append(selected)
                    try:
                        start = focused._entry.index("sel.first")
                        end = focused._entry.index("sel.last")
                        focused._entry.delete(start, end)
                    except Exception:
                        pass
                except Exception:
                    pass
            return "break"

        if event.keysym in ('Return', 'KP_Enter'):
            if hasattr(self, 'url_entry') and (focused == self.url_entry or focused == self.url_entry._entry):
                self.start_download_action()
                return "break"

        if event.keysym == 'Escape':
            if hasattr(self, 'url_entry') and (focused == self.url_entry or focused == self.url_entry._entry):
                self.url_entry.delete(0, ctk.END)
                return "break"

        return None
    def setup_sidebar(self):  
        import os, sys
        from PIL import Image

        def _res_path(rel_path):
            try:
                base = sys._MEIPASS
            except Exception:
                base = os.path.abspath(".")
            return os.path.join(base, rel_path)

        try:
            import ctypes
            from PIL import ImageTk
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("veyora.mediadownloader.final")
            self.iconbitmap(_res_path("logo.ico"))
            _taskbar_icon = ImageTk.PhotoImage(Image.open(_res_path("logo.png")))
            self.wm_iconphoto(True, _taskbar_icon)
            self._taskbar_icon_ref = _taskbar_icon
        except Exception:
            pass
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(6, weight=1)

        try:
            _pil_img = Image.open(_res_path("logo.png"))
            self.top_logo_img = ctk.CTkImage(light_image=_pil_img, dark_image=_pil_img, size=(140, 140))
            self.logo_label = ctk.CTkLabel(self.sidebar, image=self.top_logo_img, text="")
        except Exception:
            self.logo_label = ctk.CTkLabel(self.sidebar, text="Veyora", font=ctk.CTkFont(size=24, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 15))

        self.btn_dashboard = ctk.CTkButton(self.sidebar, text="Dashboard", command=lambda: self.show_tab("Dashboard"), anchor="w")
        self.btn_dashboard.grid(row=1, column=0, padx=20, pady=10, sticky="ew")

        self.btn_downloads = ctk.CTkButton(self.sidebar, text="Downloads", command=lambda: self.show_tab("Downloads"), anchor="w")
        self.btn_downloads.grid(row=2, column=0, padx=20, pady=10, sticky="ew")

        self.btn_history = ctk.CTkButton(self.sidebar, text="History", command=lambda: self.show_tab("History"), anchor="w")
        self.btn_history.grid(row=3, column=0, padx=20, pady=10, sticky="ew")

        self.btn_settings = ctk.CTkButton(self.sidebar, text="Settings", command=lambda: self.show_tab("Settings"), anchor="w")
        self.btn_settings.grid(row=4, column=0, padx=20, pady=10, sticky="ew")

        ffmpeg_ok = check_ffmpeg()
        ffmpeg_text = "FFmpeg: OK" if ffmpeg_ok else "FFmpeg: Missing"
        ffmpeg_color = "#2ecc71" if ffmpeg_ok else "#e74c3c"
        self.ffmpeg_label = ctk.CTkLabel(self.sidebar, text=ffmpeg_text, text_color=ffmpeg_color, font=ctk.CTkFont(size=11))
        self.ffmpeg_label.grid(row=5, column=0, padx=20, pady=10, sticky="w")

        try:
            _pil_img_btm = Image.open(_res_path("logo.png"))
            self.bottom_logo_img = ctk.CTkImage(light_image=_pil_img_btm, dark_image=_pil_img_btm, size=(115, 115))
            self.bottom_logo_label = ctk.CTkLabel(self.sidebar, image=self.bottom_logo_img, text="")
            self.bottom_logo_label.grid(row=6, column=0, padx=20, pady=(15, 5), sticky="s")
        except Exception:
            pass

        self.platforms_label = ctk.CTkLabel(self.sidebar, text=f"Platforms: {len(SUPPORTED_PLATFORMS)}+", text_color="gray", font=ctk.CTkFont(size=11))
        self.platforms_label.grid(row=7, column=0, padx=20, pady=5, sticky="w")

        self.theme_menu = ctk.CTkOptionMenu(self.sidebar, values=["Dark", "Light", "System"], command=self.change_theme)
        self.theme_menu.set(self.settings.get("theme", "Dark"))
        self.theme_menu.grid(row=8, column=0, padx=20, pady=20, sticky="ew")

    def setup_main_content(self):
        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.content_frame.grid_rowconfigure(0, weight=1)

    def show_tab(self, name):
        self.active_tab = name
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        self.card_widgets.clear()
        self._card_buttons.clear()
        self._card_snapshots.clear()
        self._card_progress_bars.clear()
        self._card_info_labels.clear()
        self._card_title_labels.clear()

        if name == "Dashboard":
            self.build_dashboard_tab()
        elif name == "Downloads":
            self.build_downloads_tab()
        elif name == "History":
            self.build_history_tab()
        elif name == "Settings":
            self.build_settings_tab()

    # --- DASHBOARD TAB ---
    def build_dashboard_tab(self):
        frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(frame, text="Universal Media Downloader", font=ctk.CTkFont(size=26, weight="bold"))
        title.grid(row=0, column=0, pady=(20, 10), sticky="w")

        subtitle = ctk.CTkLabel(frame, text="YouTube, Pinterest / pin.it, TikTok, Instagram, Facebook, X, Reddit, Vimeo and more. Paste a public video link; source restrictions may apply.", text_color="gray", wraplength=700)
        subtitle.grid(row=1, column=0, pady=(0, 20), sticky="w")
        ctk.CTkButton(frame, text='Sites / Pinterest', width=150, command=self.show_supported_sites).grid(row=0, column=0, sticky='e', padx=10, pady=20)

        input_card = ctk.CTkFrame(frame)
        input_card.grid(row=2, column=0, sticky="ew", pady=10)
        input_card.grid_columnconfigure(0, weight=1)

        self.url_entry = ctk.CTkEntry(input_card, placeholder_text="Paste any social media URL (YouTube, TikTok, Instagram, Facebook, Twitter, etc.)...", height=45, font=ctk.CTkFont(size=14, family="Segoe UI"))
        self.url_entry.grid(row=0, column=0, padx=15, pady=15, sticky="ew")

        # Right-click context menu
        self.url_entry.bind("<Button-3>", self.show_url_context_menu)

        btn_parse = ctk.CTkButton(input_card, text="Paste Link", height=45, width=140, font=ctk.CTkFont(size=14, weight="bold"), command=self.paste_link_action)
        btn_parse.grid(row=0, column=1, padx=5, pady=15)

        btn_download = ctk.CTkButton(input_card, text="Download", height=45, width=120, font=ctk.CTkFont(size=14, weight="bold"), command=self.start_download_action, fg_color="#2ecc71", hover_color="#27ae60")
        btn_download.grid(row=0, column=2, padx=15, pady=15)

        # Smart Mode
        smart_frame = ctk.CTkFrame(frame)
        smart_frame.grid(row=3, column=0, sticky="ew", pady=10)
        smart_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(smart_frame, text="Smart Mode", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, padx=20, pady=15, sticky="w")
        self.smart_mode_switch = ctk.CTkSwitch(smart_frame, text="One-Click Download", command=self.toggle_smart_mode)
        self.smart_mode_switch.grid(row=0, column=1, padx=20, pady=15, sticky="e")
        if self.smart_mode:
            self.smart_mode_switch.select()

        # Quick Preferences
        opts_card = ctk.CTkFrame(frame)
        opts_card.grid(row=4, column=0, sticky="ew", pady=10)

        ctk.CTkLabel(opts_card, text="Quick Preferences", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, padx=20, pady=15, sticky="w")

        self.mode_var = ctk.StringVar(value="Video")
        mode_switch = ctk.CTkSegmentedButton(opts_card, values=["Video", "Audio (Extract)"], variable=self.mode_var, command=self.on_mode_change)
        mode_switch.grid(row=1, column=0, padx=20, pady=10, sticky="w")

        self.quality_var = ctk.StringVar(value=self.settings.get("quality", "Best Available (4K/HD)"))
        qual_menu = ctk.CTkOptionMenu(opts_card, values=["Best Available (4K/HD)", "2160p (4K)", "1440p (2K)", "1080p (Full HD)", "720p (HD)", "480p"], variable=self.quality_var)
        qual_menu.grid(row=1, column=1, padx=20, pady=10, sticky="w")

        self.format_var = ctk.StringVar(value=self.settings.get("format", "MP4"))
        fmt_menu = ctk.CTkOptionMenu(opts_card, values=["MP4", "MKV", "MOV", "WEBM"], variable=self.format_var)
        fmt_menu.grid(row=1, column=2, padx=20, pady=10, sticky="w")

        # Audio format selection
        self.audio_format_frame = ctk.CTkFrame(opts_card, fg_color="transparent")
        self.audio_format_frame.grid(row=2, column=0, columnspan=3, sticky="ew", padx=20, pady=5)

        self.audio_format_label = ctk.CTkLabel(self.audio_format_frame, text="Audio Format:", font=ctk.CTkFont(size=13))
        self.audio_format_label.grid(row=0, column=0, padx=(0, 10), pady=5, sticky="w")

        self.audio_format_var = ctk.StringVar(value="Best Available")
        self.audio_format_menu = ctk.CTkOptionMenu(self.audio_format_frame, values=["Best Available"], variable=self.audio_format_var, width=250)
        self.audio_format_menu.grid(row=0, column=1, padx=10, pady=5, sticky="w")

        self.audio_bitrate_var = ctk.StringVar(value=self.settings.get("audio_bitrate", "320 kbps"))
        self.audio_bitrate_menu = ctk.CTkOptionMenu(self.audio_format_frame, values=["320 kbps", "256 kbps", "192 kbps", "128 kbps", "96 kbps"], variable=self.audio_bitrate_var, width=120)
        self.audio_bitrate_menu.grid(row=0, column=2, padx=10, pady=5, sticky="w")

        if self.mode_var.get() != "Audio (Extract)":
            self.audio_format_frame.grid_remove()

        # Arabic Subtitles UI
        self.sub_var = ctk.BooleanVar(value=self.settings.get("download_subs", False))
        sub_check = ctk.CTkCheckBox(opts_card, text="Download Subtitles (تحميل الترجمة)", variable=self.sub_var)
        sub_check.grid(row=3, column=0, padx=20, pady=10, sticky="w")

        self.sub_lang_var = ctk.StringVar(value=self.settings.get("sub_lang", "ar"))
        sub_display_map = {value: key for key, value in SUBTITLE_CHOICES.items()}
        self.sub_lang_var.set(sub_display_map.get(self.settings.get('sub_lang', 'auto-ar'), 'Auto-Translate: English -> Arabic'))
        sub_lang_menu = ctk.CTkOptionMenu(opts_card, values=list(SUBTITLE_CHOICES), variable=self.sub_lang_var, width=270)
        sub_lang_menu.grid(row=3, column=1, padx=20, pady=10, sticky="w")

        self.dashboard_subtitle_mode = ctk.StringVar(value=self.settings.get('subtitle_mode', 'separate'))
        ctk.CTkOptionMenu(opts_card, values=['separate', 'embed', 'burn', 'both'], variable=self.dashboard_subtitle_mode).grid(row=4, column=1, padx=20, pady=8, sticky='w')
        ctk.CTkLabel(opts_card, text='Subtitle output: separate / track / burn / SRT + track').grid(row=4, column=0, padx=20, pady=8, sticky='w')

        # Choose Download Folder
        folder_card = ctk.CTkFrame(frame)
        folder_card.grid(row=5, column=0, sticky="ew", pady=10)
        folder_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(folder_card, text="Save To:", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, padx=20, pady=15, sticky="w")

        self.folder_path_label = ctk.CTkLabel(folder_card, text=self.selected_folder, text_color="gray", font=ctk.CTkFont(size=12), anchor="w")
        self.folder_path_label.grid(row=0, column=1, padx=10, pady=15, sticky="ew")

        btn_browse = ctk.CTkButton(folder_card, text="Browse / Choose Folder", width=180, height=32, command=self.browse_folder)
        btn_browse.grid(row=0, column=2, padx=10, pady=15)

        btn_open_folder = ctk.CTkButton(folder_card, text="Open Folder", width=120, height=32, fg_color="#3498db", hover_color="#2980b9", command=self.open_selected_folder)
        btn_open_folder.grid(row=0, column=3, padx=10, pady=15)

    def show_supported_sites(self):
        window = ctk.CTkToplevel(self)
        window.title('Sites and Pinterest links')
        window.geometry('620x420')
        text = ctk.CTkTextbox(window, wrap='word')
        text.pack(fill='both', expand=True, padx=18, pady=18)
        text.insert('1.0', 'POPULAR SITES / ROUTING\n\n' + ', '.join(POPULAR_SITES)
            + '\n\nPinterest: paste a public video pin URL or pin.it link. Image-only pins are not videos.'
            + '\n\nOther HTTP(S) video pages and direct media URLs are also passed to yt-dlp native/generic extractors.'
            + '\n\nA recognized site is not a guarantee: sites change, some content requires cookies/account access, and DRM is unsupported.'
            + '\n\nIf a metadata request fails, the app displays the actual error instead of silently returning.')
        text.configure(state='disabled')

    def on_mode_change(self, value=None):
        mode = self.mode_var.get()
        if mode == "Audio (Extract)":
            self.audio_format_frame.grid()
        else:
            self.audio_format_frame.grid_remove()

    def browse_folder(self):
        folder = filedialog.askdirectory(title="Choose Download Folder", initialdir=self.selected_folder)
        if folder:
            self.selected_folder = folder
            self.folder_path_label.configure(text=folder)
            config = load_config()
            config["download_folder"] = folder
            save_config(config)
            self.settings["download_dir"] = folder
            SettingsManager.save(self.settings)

    def open_selected_folder(self):
        open_folder_in_explorer(self.selected_folder)

    def toggle_smart_mode(self):
        self.smart_mode = self.smart_mode_switch.get()
        self.settings["smart_mode"] = self.smart_mode
        SettingsManager.save(self.settings)

    def paste_link_action(self):
        try:
            clipboard = self.clipboard_get()
            if clipboard and is_valid_url(clipboard):
                self.url_entry.delete(0, ctk.END)
                self.url_entry.insert(0, clipboard)
                self.start_download_action()
            else:
                self.url_entry.delete(0, ctk.END)
                self.url_entry.insert(0, clipboard)
        except Exception as e:
            print(f"Paste link error: {e}")

    def start_download_action(self):
        url = self.url_entry.get().strip()
        if not url:
            return

        if not is_valid_url(url):
            messagebox.showerror("Invalid link", "Paste one complete HTTP(S) video link.")
            return

        url = normalize_url(url)
        if self.smart_mode:
            task_settings = self.settings.copy()
            task_settings['quality'] = self.quality_var.get()
            task_settings['format'] = self.format_var.get()
            task_settings['extract_audio'] = (self.mode_var.get() == "Audio (Extract)")
            task_settings['subtitle_mode'] = self.dashboard_subtitle_mode.get()
            task_settings['download_subs'] = self.sub_var.get()
            sub_lang_display = self.sub_lang_var.get()
            task_settings['sub_lang'] = selected_subtitle_language(sub_lang_display)

            if task_settings['extract_audio']:
                self.fetch_metadata_for_audio(url, task_settings)
            else:
                self.queue_manager.add_task(url, task_settings, title="Resolving...", selected_folder=self.selected_folder)
                self.show_tab("Downloads")
            return

        self.fetch_and_show_metadata(url)

    def fetch_metadata_for_audio(self, url, task_settings):
        def worker():
            info = DownloadEngine.fetch_metadata(url, self.settings.get("cookies_file", ""))
            self._ui_callbacks.put(lambda: self.handle_audio_metadata(url, info, task_settings))
        threading.Thread(target=worker, daemon=True).start()

    def handle_audio_metadata(self, url, info, task_settings):
        if not info or 'error' in info:
            self.queue_manager.add_task(url, task_settings, title="Resolving...", selected_folder=self.selected_folder)
            self.show_tab("Downloads")
            return

        if info.get('type') == 'playlist':
            self.show_playlist_selector(url, info)
            return

        audio_formats = info.get('audio_formats', [])
        if not audio_formats:
            self.queue_manager.add_task(url, task_settings, title=info.get('title', 'Resolving...'), selected_folder=self.selected_folder, thumbnail=info.get('thumbnail', ''))
            self.show_tab("Downloads")
            return

        self.show_audio_format_selector(url, info, audio_formats, task_settings)

    def show_audio_format_selector(self, url, info, audio_formats, task_settings):
        if self.audio_format_window and self.audio_format_window.winfo_exists():
            self.audio_format_window.destroy()

        self.audio_format_window = ctk.CTkToplevel(self)
        self.audio_format_window.title(f"Select Audio Format")
        self.audio_format_window.geometry("500x450")
        self.audio_format_window.transient(self)

        platform_name = info.get('platform', detect_platform(url))
        header = ctk.CTkLabel(self.audio_format_window, text=f"Platform: {platform_name}\nChoose audio format for:\n{info['title']}", font=ctk.CTkFont(size=13, weight="bold"), wraplength=460)
        header.pack(pady=15, padx=20, anchor="w")

        scroll = ctk.CTkScrollableFrame(self.audio_format_window)
        scroll.pack(fill="both", expand=True, padx=20, pady=10)

        selected_format = ctk.StringVar(value="best")

        best_rb = ctk.CTkRadioButton(scroll, text="Best Available (auto-select highest quality)", variable=selected_format, value="best")
        best_rb.pack(anchor="w", pady=5)

        for af in audio_formats:
            ext = af.get('ext', 'unknown')
            abr = af.get('abr', 0)
            filesize = af.get('filesize', 0)
            size_str = f" ({filesize / (1024*1024):.1f} MB)" if filesize > 0 else ""
            label = f"{ext.upper()} - {abr} kbps{size_str}  [ID: {af['format_id']}]"
            rb = ctk.CTkRadioButton(scroll, text=label, variable=selected_format, value=af['format_id'])
            rb.pack(anchor="w", pady=3)

        def download_with_format():
            chosen = selected_format.get()
            if chosen != "best":
                task_settings['audio_format_id'] = chosen
                for af in audio_formats:
                    if af['format_id'] == chosen:
                        task_settings['audio_format'] = af['ext'].upper()
                        break
            else:
                task_settings['audio_format_id'] = ''

            self.audio_format_window.destroy()
            self.queue_manager.add_task(url, task_settings, title=info.get('title', 'Resolving...'), selected_folder=self.selected_folder, thumbnail=info.get('thumbnail', ''))
            self.show_tab("Downloads")

        btn_download = ctk.CTkButton(self.audio_format_window, text="Download", command=download_with_format, fg_color="#2ecc71", hover_color="#27ae60")
        btn_download.pack(pady=15, padx=20)

    def fetch_and_show_metadata(self, url):
        def worker():
            info = DownloadEngine.fetch_metadata(url, self.settings.get("cookies_file", ""))
            self._ui_callbacks.put(lambda: self.handle_metadata_result(url, info))
        threading.Thread(target=worker, daemon=True).start()

    def handle_metadata_result(self, url, info):
        if not info:
            task_settings = self.settings.copy()
            task_settings['quality'] = self.quality_var.get()
            task_settings['format'] = self.format_var.get()
            task_settings['extract_audio'] = (self.mode_var.get() == "Audio (Extract)")
            task_settings['subtitle_mode'] = self.dashboard_subtitle_mode.get()
            task_settings['download_subs'] = self.sub_var.get()
            sub_lang_display = self.sub_lang_var.get()
            task_settings['sub_lang'] = selected_subtitle_language(sub_lang_display)

            if task_settings['extract_audio']:
                self.fetch_metadata_for_audio(url, task_settings)
            else:
                self.queue_manager.add_task(url, task_settings, title="Resolving...", selected_folder=self.selected_folder)
                self.show_tab("Downloads")
            return

        if 'error' in info:
            messagebox.showerror('Could not read this link', info['error'])
            return

        if info.get('type') == 'playlist':
            self.show_playlist_selector(url, info)
        else:
            task_settings = self.settings.copy()
            task_settings['quality'] = self.quality_var.get()
            task_settings['format'] = self.format_var.get()
            task_settings['extract_audio'] = (self.mode_var.get() == "Audio (Extract)")
            task_settings['subtitle_mode'] = self.dashboard_subtitle_mode.get()
            task_settings['download_subs'] = self.sub_var.get()
            sub_lang_display = self.sub_lang_var.get()
            task_settings['sub_lang'] = selected_subtitle_language(sub_lang_display)

            if task_settings['extract_audio']:
                audio_formats = info.get('audio_formats', [])
                if audio_formats:
                    self.show_audio_format_selector(url, info, audio_formats, task_settings)
                else:
                    self.queue_manager.add_task(url, task_settings, title=info.get('title', 'Resolving...'), selected_folder=self.selected_folder, thumbnail=info.get('thumbnail', ''))
                    self.show_tab("Downloads")
            else:
                self.queue_manager.add_task(url, task_settings, title=info.get('title', 'Resolving...'), selected_folder=self.selected_folder, video_id=info.get('id', ''), thumbnail=info.get('thumbnail', ''))
                self.show_tab("Downloads")

    def show_playlist_selector(self, url, info):
        if self.playlist_window and self.playlist_window.winfo_exists():
            self.playlist_window.destroy()

        platform_name = info.get('platform', detect_platform(url))
        self.playlist_window = ctk.CTkToplevel(self)
        self.playlist_window.title(f"Playlist: {info['title']}")
        self.playlist_window.geometry("600x500")
        self.playlist_window.transient(self)

        header = ctk.CTkLabel(self.playlist_window, text=f"Platform: {platform_name}\n{info['title']} ({info['count']} videos)", font=ctk.CTkFont(size=16, weight="bold"), wraplength=560)
        header.pack(pady=15, padx=20, anchor="w")

        select_all_var = ctk.BooleanVar(value=True)
        select_all_cb = ctk.CTkCheckBox(self.playlist_window, text="Select All", variable=select_all_var)
        select_all_cb.pack(pady=5, padx=20, anchor="w")

        scroll = ctk.CTkScrollableFrame(self.playlist_window)
        scroll.pack(fill="both", expand=True, padx=20, pady=10)

        checkboxes = []
        for entry in info['entries']:
            var = ctk.BooleanVar(value=True)
            duration = entry.get('duration', 0) or 0
            display_title = fix_arabic_text(entry['title'])
            cb = ctk.CTkCheckBox(scroll, text=f"{display_title} ({duration//60}:{duration%60:02d})", variable=var, font=ctk.CTkFont(family="Segoe UI", size=12))
            cb.pack(anchor="w", pady=2)
            checkboxes.append((entry, var))

        def toggle_all():
            for _, var in checkboxes:
                var.set(select_all_var.get())

        select_all_cb.configure(command=toggle_all)

        def download_selected():
            selected = [entry for entry, var in checkboxes if var.get()]
            if not selected:
                return
            task_settings = self.settings.copy()
            task_settings['quality'] = self.quality_var.get()
            task_settings['format'] = self.format_var.get()
            task_settings['extract_audio'] = (self.mode_var.get() == "Audio (Extract)")
            task_settings['subtitle_mode'] = self.dashboard_subtitle_mode.get()
            task_settings['download_subs'] = self.sub_var.get()
            sub_lang_display = self.sub_lang_var.get()
            task_settings['sub_lang'] = selected_subtitle_language(sub_lang_display)

            for entry in selected:
                entry_url = entry.get('url', '')
                if not entry_url:
                    entry_url = entry_page_url(entry, info.get('platform', ''))
                if entry_url:
                    self.queue_manager.add_task(entry_url, task_settings, title=entry['title'], selected_folder=self.selected_folder, video_id=entry.get('id', ''))

            self.playlist_window.destroy()
            self.show_tab("Downloads")

        btn_download = ctk.CTkButton(self.playlist_window, text=f"Download Selected", command=download_selected, fg_color="#2ecc71", hover_color="#27ae60")
        btn_download.pack(pady=15, padx=20)

    # --- DOWNLOADS TAB ---
    def build_downloads_tab(self):
        frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(20, 10))
        header.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(header, text="Downloads", font=ctk.CTkFont(size=26, weight="bold"))
        title.grid(row=0, column=0, sticky="w")

        filter_frame = ctk.CTkFrame(header, fg_color="transparent")
        filter_frame.grid(row=1, column=0, sticky="w", pady=10)

        self.filter_buttons = {}
        for i, (label, value) in enumerate([("All", "all"), ("Downloading", "downloading"), ("Completed", "completed"), ("Failed", "failed")]):
            btn = ctk.CTkButton(filter_frame, text=label, width=100, height=30,
                                command=lambda v=value: self.set_filter(v),
                                fg_color="transparent" if value != self.active_filter else "#3b8ed0",
                                border_width=1, border_color="#3b8ed0")
            btn.grid(row=0, column=i, padx=5)
            self.filter_buttons[value] = btn

        bulk_frame = ctk.CTkFrame(header, fg_color="transparent")
        bulk_frame.grid(row=0, column=1, sticky="e")

        btn_clear = ctk.CTkButton(bulk_frame, text="Clear Completed", width=130, height=30, command=self.clear_completed)
        btn_clear.grid(row=0, column=0, padx=5)

        self.downloads_scroll = ctk.CTkScrollableFrame(frame, corner_radius=10)
        self.downloads_scroll.grid(row=2, column=0, sticky="nsew", pady=10)
        self.downloads_scroll.grid_columnconfigure(0, weight=1)

        self.status_bar = ctk.CTkFrame(frame, height=30)
        self.status_bar.grid(row=3, column=0, sticky="ew", pady=(5, 0))
        self.status_label = ctk.CTkLabel(self.status_bar, text="Ready", font=ctk.CTkFont(size=12))
        self.status_label.pack(side="left", padx=15)

        self.render_download_items()

    def set_filter(self, filter_value):
        self.active_filter = filter_value
        for value, btn in self.filter_buttons.items():
            if value == filter_value:
                btn.configure(fg_color="#3b8ed0")
            else:
                btn.configure(fg_color="transparent")
        self.render_download_items()

    def clear_completed(self):
        tasks = self.queue_manager.get_tasks_by_status("completed")
        for task in tasks:
            self.queue_manager.remove_task(task['id'])
        self.render_download_items()

    def render_download_items(self):
        tasks = self.queue_manager.get_tasks_by_status(self.active_filter)
        visible = {t['id'] for t in tasks}
        all_tasks = self.queue_manager.get_tasks_by_status()
        existing = {t['id'] for t in all_tasks}
        for tid in list(self.card_widgets):
            if tid not in existing:
                self.card_widgets.pop(tid).destroy()
                for cache in (self._card_progress_bars, self._card_info_labels,
                              self._card_title_labels, self._card_buttons, self._card_snapshots):
                    cache.pop(tid, None)
            elif tid not in visible:
                self.card_widgets[tid].grid_remove()
        for index, task in enumerate(tasks):
            tid = task['id']
            if tid not in self.card_widgets:
                self.create_download_card(task, index)
            else:
                self.card_widgets[tid].grid(row=index)
            self._update_download_card(task)
        if not hasattr(self, '_empty_download_label') or not self._empty_download_label.winfo_exists():
            self._empty_download_label = ctk.CTkLabel(self.downloads_scroll, text="No downloads in this category.")
        if tasks:
            self._empty_download_label.grid_remove()
        else:
            self._empty_download_label.grid(row=0, column=0, pady=40)
        active = sum(t['status'] not in self.queue_manager.TERMINAL for t in all_tasks)
        completed = sum(t['status'] == 'Completed' for t in all_tasks)
        self.status_label.configure(text=f"Active: {active} | Completed: {completed} | Total: {len(all_tasks)}")

    def _update_download_card(self, task):
        tid, status = task['id'], task['status']
        old = self._card_snapshots.get(tid, {})
        title = fix_arabic_text(task['title'])
        text = f"Status: {status} | Size: {task.get('filesize', 0)/1048576:.1f} MB"
        if status == 'Translating':
            text += ' | ' + task.get('stage', 'Preparing translation')
        if status == 'Downloading':
            text += f" | Speed: {task['speed']} | ETA: {task['eta']}"
        if task.get('error'):
            text = f"Error: {task['error'][:160]}"
        if title != old.get('title'):
            self._card_title_labels[tid].configure(text=title)
        if text != old.get('text'):
            self._card_info_labels[tid].configure(text=text)
        if task['progress'] != old.get('progress'):
            self._card_progress_bars[tid].set(task['progress'])
        if status != old.get('status'):
            buttons = self._card_buttons[tid]
            for button in buttons.values():
                button.pack_forget()
            actions = {
                'Queued': ('pause', 'cancel'), 'Downloading': ('pause', 'cancel'),
                'Paused': ('resume', 'cancel'), 'Processing / Muxing': ('cancel',),
                'Translating': ('cancel',), 'Failed': ('retry', 'remove'),
                'Cancelled': ('retry', 'remove'), 'Completed': ('show', 'remove'),
            }.get(status, ())
            for action in actions:
                buttons[action].pack(pady=2)
        self._card_snapshots[tid] = dict(title=title, text=text, progress=task['progress'], status=status)

    def create_download_card(self, task, idx):
        card = ctk.CTkFrame(self.downloads_scroll, corner_radius=10)
        card.grid(row=idx, column=0, sticky="ew", padx=10, pady=8)
        card.grid_columnconfigure(1, weight=1)

        thumb_frame = ctk.CTkFrame(card, width=120, height=68, corner_radius=8)
        thumb_frame.grid(row=0, column=0, rowspan=3, padx=10, pady=10, sticky="n")
        thumb_frame.grid_propagate(False)

        format_badge = task.get('format_badge', '')
        if not format_badge:
            if task['settings'].get('extract_audio', False):
                audio_fmt = task['settings'].get('audio_format', 'MP3')
                format_badge = f"Audio {audio_fmt}"
            else:
                quality = task['settings'].get('quality', 'Best')
                fmt = task['settings'].get('format', 'MP4')
                if '4K' in quality or '2160' in quality:
                    format_badge = f"{fmt} 4K"
                elif '1080' in quality:
                    format_badge = f"{fmt} 1080p"
                elif '720' in quality:
                    format_badge = f"{fmt} 720p"
                else:
                    format_badge = f"{fmt} Best"
            task['format_badge'] = format_badge

        badge_label = ctk.CTkLabel(thumb_frame, text=format_badge, font=ctk.CTkFont(size=10, weight="bold"), text_color="white")
        badge_label.place(relx=0.5, rely=0.5, anchor="center")

        display_title = fix_arabic_text(task['title'])
        lbl_title = ctk.CTkLabel(card, text=display_title, font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"), anchor="w", wraplength=400)
        lbl_title.grid(row=0, column=1, padx=10, pady=(10, 2), sticky="w")
        self._card_title_labels[task['id']] = lbl_title

        info_text = f"Status: {task['status']}"
        if task.get('filesize', 0) > 0:
            size_mb = task['filesize'] / (1024 * 1024)
            info_text += f" | Size: {size_mb:.1f} MB"
        if task['status'] in ('Downloading', 'Processing / Muxing', 'Merging & Processing (FFmpeg)...'):
            info_text += f" | Speed: {task['speed']} | ETA: {task['eta']}"

        if task['error']:
            info_text = f"Error: {task['error'][:80]}"

        lbl_info = ctk.CTkLabel(card, text=info_text, text_color="gray", font=ctk.CTkFont(family="Segoe UI", size=12), anchor="w", wraplength=450, justify="left")
        lbl_info.grid(row=1, column=1, padx=10, pady=2, sticky="w")
        self._card_info_labels[task['id']] = lbl_info

        prog = ctk.CTkProgressBar(card)
        prog.set(task['progress'])
        prog.grid(row=2, column=1, padx=10, pady=(2, 10), sticky="ew")
        self._card_progress_bars[task['id']] = prog

        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.grid(row=0, column=2, rowspan=3, padx=10, pady=10, sticky="n")

        tid = task['id']
        self.card_widgets[tid] = card
        actions = {
            'pause': ('Pause', lambda: self.queue_manager.pause_task(tid)),
            'resume': ('Resume', lambda: self.queue_manager.resume_task(tid)),
            'cancel': ('Cancel', lambda: self.queue_manager.cancel_task(tid)),
            'retry': ('Retry', lambda: self.queue_manager.retry_task(tid)),
            'remove': ('Remove', lambda: self.queue_manager.remove_task(tid)),
            'show': ('Show in Folder', lambda: self._show_task_file(tid)),
        }
        self._card_buttons[tid] = {
            name: ctk.CTkButton(btn_frame, text=label, width=100, height=28, command=command)
            for name, (label, command) in actions.items()
        }

    def _show_task_file(self, tid):
        task = next((t for t in self.queue_manager.get_tasks_by_status() if t['id'] == tid), None)
        if task and task.get('downloaded_file'):
            open_file_in_explorer(task['downloaded_file'])

    # --- HISTORY TAB ---
    def build_history_tab(self):
        frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        title = ctk.CTkLabel(frame, text="Download History", font=ctk.CTkFont(size=26, weight="bold"))
        title.grid(row=0, column=0, pady=(20, 10), sticky="w")

        history_scroll = ctk.CTkScrollableFrame(frame, corner_radius=10)
        history_scroll.grid(row=1, column=0, sticky="nsew", pady=10)
        history_scroll.grid_columnconfigure(0, weight=1)

        history_items = HistoryManager.load()
        if not history_items:
            ctk.CTkLabel(history_scroll, text="No completed downloads history yet.", text_color="gray", font=ctk.CTkFont(size=14)).grid(row=0, column=0, pady=40)
            return

        for idx, item in enumerate(history_items):
            card = ctk.CTkFrame(history_scroll)
            card.grid(row=idx, column=0, sticky="ew", padx=10, pady=5)
            card.grid_columnconfigure(0, weight=1)

            display_title = fix_arabic_text(item.get('title', 'Unknown'))
            ctk.CTkLabel(card, text=display_title, font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"), anchor="w").grid(row=0, column=0, padx=15, pady=(10, 2), sticky="w")
            platform_text = item.get('platform', '')
            time_text = f"Time: {item.get('time', '')}"
            if platform_text:
                time_text += f" | Platform: {platform_text}"
            ctk.CTkLabel(card, text=time_text, text_color="gray", font=ctk.CTkFont(family="Segoe UI", size=11), anchor="w").grid(row=1, column=0, padx=15, pady=(0, 2), sticky="w")

            file_path = item.get('file_path')
            if file_path and os.path.exists(file_path):
                btn_open = ctk.CTkButton(card, text="Show in Folder", command=lambda f=file_path: open_file_in_explorer(f), height=24, font=ctk.CTkFont(size=11))
                btn_open.grid(row=2, column=0, padx=15, pady=(2, 10), sticky="w")

    # --- SETTINGS TAB ---
    def build_settings_tab(self):
        frame = ctk.CTkScrollableFrame(self.content_frame, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(frame, text="Application Settings", font=ctk.CTkFont(size=26, weight="bold"))
        title.grid(row=0, column=0, pady=(20, 10), sticky="w")

        card = ctk.CTkFrame(frame)
        card.grid(row=1, column=0, sticky="ew", pady=10)
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(card, text="Output Directory:", font=ctk.CTkFont(size=14)).grid(row=0, column=0, padx=20, pady=20, sticky="w")
        self.dir_entry = ctk.CTkEntry(card, width=350)
        self.dir_entry.insert(0, self.settings.get("download_dir", ""))
        self.dir_entry.grid(row=0, column=1, padx=20, pady=20, sticky="ew")

        ctk.CTkLabel(card, text="Max Concurrent Downloads:", font=ctk.CTkFont(size=14)).grid(row=1, column=0, padx=20, pady=10, sticky="w")
        self.concurrent_var = ctk.StringVar(value=str(self.settings.get("max_concurrent", 3)))
        concurrent_menu = ctk.CTkOptionMenu(card, values=["1", "2", "3", "4", "5"], variable=self.concurrent_var)
        concurrent_menu.grid(row=1, column=1, padx=20, pady=10, sticky="w")

        self.sub_var = ctk.BooleanVar(value=self.settings.get("download_subs", False))
        sub_check = ctk.CTkCheckBox(card, text="Download Subtitles Automatically", variable=self.sub_var)
        sub_check.grid(row=2, column=0, columnspan=2, padx=20, pady=10, sticky="w")

        self.thumb_var = ctk.BooleanVar(value=self.settings.get("save_thumbnail", True))
        thumb_check = ctk.CTkCheckBox(card, text="Save Video Thumbnails", variable=self.thumb_var)
        thumb_check.grid(row=3, column=0, columnspan=2, padx=20, pady=10, sticky="w")

        ctk.CTkLabel(card, text="Cookies File (optional):", font=ctk.CTkFont(size=14)).grid(row=4, column=0, padx=20, pady=10, sticky="w")
        self.cookies_entry = ctk.CTkEntry(card, width=350, placeholder_text="Path to cookies.txt (Netscape format)")
        self.cookies_entry.insert(0, self.settings.get("cookies_file", ""))
        self.cookies_entry.grid(row=4, column=1, padx=20, pady=10, sticky="ew")

        btn_save = ctk.CTkButton(card, text="Save Settings", command=self.save_settings_action)
        ctk.CTkLabel(card, text="Subtitle source:").grid(row=5, column=0, padx=20, pady=8, sticky="w")
        self.translation_source_var = ctk.StringVar(value=self.settings.get('sub_lang', 'auto-ar'))
        ctk.CTkOptionMenu(card, values=[k for k in TRANSLATION_DIRECTIONS if k != 'auto'] + list(LANGUAGES), variable=self.translation_source_var).grid(row=5, column=1, padx=20, pady=8, sticky="w")
        ctk.CTkLabel(card, text="auto-ar: English -> Arabic | auto-en: Arabic -> English").grid(row=6, column=0, columnspan=2, padx=20, sticky="w")
        self.subtitle_mode_var = ctk.StringVar(value=self.settings.get('subtitle_mode', 'separate'))
        ctk.CTkLabel(card, text="Subtitle output:").grid(row=7, column=0, padx=20, pady=8, sticky="w")
        ctk.CTkOptionMenu(card, values=['separate', 'embed', 'burn', 'both'], variable=self.subtitle_mode_var).grid(row=7, column=1, padx=20, pady=8, sticky="w")
        ctk.CTkLabel(card, text="Separate SRT / selectable track / burned into picture / SRT + track").grid(row=8, column=0, columnspan=2, padx=20, sticky="w")
        ctk.CTkLabel(card, text="Local Arabic, English, Turkish and Korean subtitles. Some pairs translate via English. Models download once.", wraplength=650).grid(row=9, column=0, columnspan=2, padx=20, pady=8, sticky="w")
        btn_save.grid(row=10, column=0, columnspan=2, padx=20, pady=12)
        ctk.CTkButton(card, text="Check for Updates", command=lambda: self.updater.check(True)).grid(row=11, column=0, padx=20, pady=10)
        def update_setting(key, value):
            self.settings[key] = value
            SettingsManager.save(self.settings)
        auto_check = ctk.BooleanVar(value=self.settings.get('auto_update_check', True))
        ctk.CTkCheckBox(card, text='Check on startup', variable=auto_check, command=lambda:update_setting('auto_update_check',auto_check.get())).grid(row=13,column=0,pady=8)
        performance = ctk.StringVar(value=self.settings.get('performance_mode','balanced'))
        def set_performance(value):
            from performance import PROFILES
            update_setting('performance_mode',value)
            os.environ['VEYORA_PERFORMANCE']=value
            self.settings['max_concurrent']=PROFILES[value][1]
            SettingsManager.save(self.settings)
            self.queue_manager.set_max_concurrent(PROFILES[value][1])
        ctk.CTkOptionMenu(card, values=['economy','balanced','high'], variable=performance, command=set_performance).grid(row=13,column=1,pady=8)
        pre = ctk.BooleanVar(value=self.settings.get('allow_prereleases', False))
        ctk.CTkCheckBox(card, text="Allow prerelease updates", variable=pre, command=lambda:update_setting('allow_prereleases',pre.get())).grid(row=11,column=1,pady=10)
        original = ctk.BooleanVar(value=self.settings.get('save_original_subtitles', False))
        ctk.CTkCheckBox(card, text="Also save original transcript", variable=original, command=lambda:update_setting('save_original_subtitles',original.get())).grid(row=12,column=0,columnspan=2,pady=10)


        ctk.CTkLabel(card,text='Speech model: base / small / medium (larger uses more RAM)').grid(row=14,column=0,padx=20,pady=8)
        speech=ctk.StringVar(value=self.settings.get('speech_model','base'))
        ctk.CTkOptionMenu(card,values=['base','small','medium'],variable=speech,command=lambda v:update_setting('speech_model',v)).grid(row=14,column=1,pady=8)

    def save_settings_action(self):
        self.settings["download_dir"] = self.dir_entry.get()
        self.settings["download_subs"] = self.sub_var.get()
        self.settings["save_thumbnail"] = self.thumb_var.get()
        self.settings["max_concurrent"] = int(self.concurrent_var.get())
        self.settings["cookies_file"] = self.cookies_entry.get()
        self.settings['sub_lang'] = self.translation_source_var.get()
        self.settings['subtitle_mode'] = self.subtitle_mode_var.get()
        self.selected_folder = self.settings['download_dir']
        Path(self.selected_folder).mkdir(parents=True, exist_ok=True)
        save_config({'download_folder': self.selected_folder})
        SettingsManager.save(self.settings)
        self.queue_manager.set_max_concurrent(self.settings["max_concurrent"])

    def change_theme(self, new_theme):
        self.settings["theme"] = new_theme
        SettingsManager.save(self.settings)
        ctk.set_appearance_mode(new_theme)

    # === RIGHT-CLICK CONTEXT MENU ===
    def show_url_context_menu(self, event):
        import tkinter as tk
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Paste", command=self._ctx_paste)
        menu.add_command(label="Copy", command=self._ctx_copy)
        menu.add_command(label="Cut", command=self._ctx_cut)
        menu.add_separator()
        menu.add_command(label="Select All", command=self._ctx_select_all)
        menu.add_command(label="Clear", command=self._ctx_clear)
        menu.post(event.x_root, event.y_root)

    def _ctx_paste(self):
        try:
            clipboard = self.clipboard_get()
            try:
                start = self.url_entry.index("sel.first")
                end = self.url_entry.index("sel.last")
                self.url_entry.delete(start, end)
            except Exception:
                pass
            cursor_pos = self.url_entry.index("insert")
            self.url_entry.insert(cursor_pos, clipboard)
        except Exception as e:
            print(f"Context paste error: {e}")

    def _ctx_copy(self):
        try:
            selected = self.url_entry.selection_get()
            self.clipboard_clear()
            self.clipboard_append(selected)
        except Exception:
            pass

    def _ctx_cut(self):
        try:
            selected = self.url_entry.selection_get()
            self.clipboard_clear()
            self.clipboard_append(selected)
            try:
                start = self.url_entry.index("sel.first")
                end = self.url_entry.index("sel.last")
                self.url_entry.delete(start, end)
            except Exception:
                pass
        except Exception:
            pass

    def _ctx_select_all(self):
        self.url_entry.select_range(0, 'end')
        self.url_entry.icursor('end')

    def _ctx_clear(self):
        self.url_entry.delete(0, ctk.END)

    # === GLOBAL PASTE HANDLER ===
    def global_paste_handler(self, event=None):
        try:
            focused = self.focus_get()
            if focused == self.url_entry._entry or focused == self.url_entry:
                return
        except Exception:
            pass

        try:
            clipboard = self.clipboard_get()
            if clipboard and is_valid_url(clipboard):
                self.url_entry.delete(0, ctk.END)
                self.url_entry.insert(0, clipboard)
                self.start_download_action()
        except Exception as e:
            print(f"Global paste error: {e}")

    def paste_link_action(self):
        try:
            clipboard = self.clipboard_get()
            if clipboard and is_valid_url(clipboard):
                self.url_entry.delete(0, ctk.END)
                self.url_entry.insert(0, clipboard)
                self.start_download_action()
            else:
                self.url_entry.delete(0, ctk.END)
                self.url_entry.insert(0, clipboard)
        except Exception as e:
            print(f"Paste link error: {e}")

    def refresh_ui(self):
        if self.active_tab == "Downloads":
            self.render_download_items()


def packaged_self_test(report_path):
    report = {'ok': False, 'version': APP_VERSION}
    try:
        import faster_whisper
        import ctranslate2
        import onnxruntime
        onnxruntime.disable_telemetry_events()
        import av
        import sentencepiece
        with create_downloader({'quiet': True, 'no_warnings': True}) as engine:
            assert 'Pinterest' in engine._ies and 'Generic' in engine._ies
            assert 'PinterestShortLink' in engine._ies
        from translator.video_renderer import executable
        from translator.translation_provider import TranslatorProvider
        report['offline_translation'] = {}
        for source, target, text in [('en', 'ar', 'Hello world.'), ('ar', 'en', 'مرحبا بالعالم'), ('en', 'tr', 'Hello world.'), ('tr', 'en', 'Merhaba dünya.'), ('en', 'ko', 'Hello world.'), ('ko', 'en', '안녕하세요.')]:
            provider = TranslatorProvider(source, target)
            provider.prepare()
            translated = provider.translate(text)
            valid = (any('\u0600' <= c <= '\u06ff' for c in translated) if target == 'ar'
                     else (any('가' <= c <= '힣' for c in translated) if target == 'ko' else bool(re.search('[A-Za-z]', translated))))
            if not valid:
                raise RuntimeError('Packaged local translator failed: ' + source + ' -> ' + target)
            report['offline_translation'][source + '_' + target] = translated
        # Exercise a real installed SRT translation and MP4 render without
        # treating it as an audio-recognition test.
        from translator.pipeline import TranslationPipeline
        from translator.video_renderer import run_ffmpeg, burn_subtitles, get_ffprobe_info
        from translator.translation_provider import release_translation_models
        with tempfile.TemporaryDirectory(prefix='veyora-installed-test-') as folder:
            folder = Path(folder)
            source = folder / 'source.srt'
            source.write_text('1\n00:00:00,000 --> 00:00:00,900\nHello world.\n', encoding='utf8')
            outputs = TranslationPipeline(source, folder / 'output').run(source_lang='en', target_lang='ar')
            translated_srt = Path(outputs['subtitle']).read_text(encoding='utf8')
            if not any('\u0600' <= c <= '\u06ff' for c in translated_srt):
                raise RuntimeError('Installed SRT translation failed')
            video = folder / 'input.mp4'
            run_ffmpeg(['-f', 'lavfi', '-i', 'color=s=160x90:d=1', '-c:v', 'libx264', video])
            burned = folder / 'burned.mp4'
            burn_subtitles(video, outputs['subtitle'], burned)
            if not any(s['codec_type'] == 'video' for s in get_ffprobe_info(burned)['streams']):
                raise RuntimeError('Installed MP4 rendering failed')
            report['srt_translation_and_mp4_render'] = True
        release_translation_models()
        subprocess.run([executable('ffmpeg'), '-version'], check=True, capture_output=True, timeout=20)
        subprocess.run([executable('ffprobe'), '-version'], check=True, capture_output=True, timeout=20)
        root = ctk.CTk()
        root.withdraw()
        root.update_idletasks()
        root.destroy()
        report['ok'] = True
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    atomic_json_write(report_path, report)
    return 0 if report['ok'] else 1


def _review_guard(function,*args):
    import faulthandler
    directory=Path(args[2] if len(args)==3 else args[1])
    directory.mkdir(parents=True,exist_ok=True)
    with (directory/'native-crash.log').open('w',encoding='utf8') as crash_log:
        faulthandler.enable(file=crash_log,all_threads=True)
        try:return function(*args)
        except Exception:
            import traceback
            (directory/'review-crash.json').write_text(json.dumps(dict(error=traceback.format_exc()),ensure_ascii=True,indent=2),encoding='utf8')
            return 1
        finally:faulthandler.disable()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    if len(sys.argv)==4 and sys.argv[1]=='--review-regression-recovery':
        from regression_validation import run_regression_review
        sys.exit(run_regression_review(*sys.argv[2:]))
    if len(sys.argv)==5 and sys.argv[1]=='--review-close':
        from final_validation import run_close_review
        sys.exit(run_close_review(*sys.argv[2:]))
    if len(sys.argv)==4 and sys.argv[1]=='--review-final-ui':
        from final_validation import run_final_review
        sys.exit(run_final_review(*sys.argv[2:]))
    if len(sys.argv) == 5 and sys.argv[1] == '--review-features':
        from media_validation import gui_features_review
        sys.exit(gui_features_review(*sys.argv[2:]))
    if len(sys.argv) == 5 and sys.argv[1] == '--review-download-child':
        from media_validation import download_child
        sys.exit(download_child(*sys.argv[2:]))
    if len(sys.argv) == 4 and sys.argv[1] in ('--review-quality','--review-recovery'):
        from media_validation import quality_review,recovery_review
        review = quality_review if sys.argv[1]=='--review-quality' else recovery_review
        sys.exit(review(*sys.argv[2:]))
    if len(sys.argv) == 5 and sys.argv[1] == '--review-navigation':
        from navigation_validation import run_navigation_review
        sys.exit(_review_guard(run_navigation_review,sys.argv[2],sys.argv[3],sys.argv[4]))
    if len(sys.argv) == 5 and sys.argv[1] == '--review-video':
        from review_validation import run_video_review
        sys.exit(run_video_review(sys.argv[2], sys.argv[3], sys.argv[4]))
    if len(sys.argv) == 3 and sys.argv[1] == '--gui-smoke':
        from desktop_ui import DesktopApp
        from PIL import ImageGrab
        app = DesktopApp()
        def smoke():
            try:
                for tab in ('Dashboard','Downloads','History','Settings','Translation','Convert','Dashboard'):
                    app.show_tab(tab)
                    app.update_idletasks()
                ImageGrab.grab().save(sys.argv[2])
            finally:
                app._on_close()
        app.after(1200, smoke)
        app.mainloop()
        sys.exit(0 if Path(sys.argv[2]).is_file() else 1)
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        sys.exit(packaged_self_test(sys.argv[2]))
    if len(sys.argv) == 5 and sys.argv[1] == "--install-update":
        from updater.install import install_after_exit
        sys.exit(install_after_exit(int(sys.argv[2]), sys.argv[3], sys.argv[4], CONFIG_DIR))
    from desktop_ui import DesktopApp
    app = DesktopApp()
    app.mainloop()
