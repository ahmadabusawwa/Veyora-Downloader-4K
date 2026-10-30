import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import queue
import time
import math
from pathlib import Path
from .exceptions import FFmpegError
from .resources import processing_slot


def executable(name):
    # Bundled FFmpeg is preferred; otherwise honor PATH.
    roots = [Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent)), Path(sys.executable).parent]
    suffix = '.exe' if os.name == 'nt' else ''
    for root in roots:
        candidate = root / (name + suffix)
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name)
    if not found:
        raise FFmpegError(f'{name} is missing; install FFmpeg or place it alongside the application')
    return found


def _progress_values(packet, duration, elapsed):
    """FFmpeg out_time_us is microseconds, not milliseconds."""
    try:
        position = max(0.0, float(packet.get('out_time_us', 'N/A')) / 1_000_000)
    except (TypeError, ValueError):
        position = None
    if position is not None and not math.isfinite(position):
        position = None
    if position is None:
        try:
            hours, minutes, seconds = packet['out_time'].split(':')
            position = max(0.0, int(hours) * 3600 + int(minutes) * 60 + float(seconds))
        except (KeyError, TypeError, ValueError):
            position = None
    try:
        speed = float(str(packet.get('speed', '')).rstrip('x'))
        if not math.isfinite(speed) or speed <= 0:
            speed = None
    except (TypeError, ValueError):
        speed = None
    if speed is None and position is not None and elapsed >= 1:
        speed = position / elapsed or None
    fraction = min(.999, position / duration) if duration and position is not None else None
    eta = max(0.0, duration - position) / speed if duration and position is not None and speed else None
    return fraction, eta, speed


def run_ffmpeg(arguments, checkpoint=lambda: None, cwd=None, duration=None, progress=None, stall_timeout=300):
    """Continuously drain FFmpeg progress; retain only the latest packet."""
    with processing_slot(checkpoint):
        return _run_ffmpeg(arguments, checkpoint, cwd, duration, progress, stall_timeout)


def _run_ffmpeg(arguments, checkpoint, cwd, duration, progress, stall_timeout=300):
    packets = queue.Queue(maxsize=1)
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([executable('ffmpeg'), '-nostdin', '-n', '-hide_banner',
            '-loglevel', 'error', '-nostats', '-stats_period', '0.5', '-progress', 'pipe:1',
            *map(str, arguments)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors,
            text=True, encoding='utf-8', errors='replace', cwd=cwd,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        def reader():
            packet = {}
            try:
                for line in process.stdout:
                    key, separator, value = line.strip().partition('=')
                    if not separator:
                        continue
                    packet[key] = value
                    if key == 'progress':
                        try:
                            packets.put_nowait(packet)
                        except queue.Full:
                            try:
                                packets.get_nowait()
                            except queue.Empty:
                                pass
                            try:
                                packets.put_nowait(packet)
                            except queue.Full:
                                pass
                        packet = {}
            except (OSError, ValueError):
                pass
        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        started, last_fraction, last_speed = time.monotonic(), 0.0, None
        last_advance, last_position = time.monotonic(), None
        def update():
            nonlocal last_fraction, last_speed, last_advance, last_position
            try:
                packet = packets.get_nowait()
            except queue.Empty:
                return
            position = packet.get('out_time_us') or packet.get('out_time')
            if position and position != last_position:
                last_position, last_advance = position, time.monotonic()
            fraction, eta, speed = _progress_values(packet, duration, time.monotonic() - started)
            if fraction is not None:
                fraction = max(last_fraction, fraction)
                last_fraction = fraction
            last_speed = speed
            if progress:
                progress(fraction, eta, speed)
        try:
            while True:
                checkpoint()
                update()
                if process.poll() is not None:
                    break
                if stall_timeout and time.monotonic() - last_advance > stall_timeout:
                    raise FFmpegError('FFmpeg stopped making progress; the process was terminated')
                time.sleep(.1)
            thread.join(timeout=2)
            update()
            if process.returncode:
                errors.seek(0, os.SEEK_END)
                errors.seek(max(0, errors.tell() - 3000))
                raise FFmpegError(errors.read(3000).decode('utf-8', errors='replace').strip())
            checkpoint()
            if progress:
                progress(1.0, 0.0, last_speed)
        except BaseException:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            raise
        finally:
            thread.join(timeout=2)
            process.stdout.close()


def media_duration(video_path):
    info = get_ffprobe_info(video_path)
    try:
        value = float(info.get('format', {}).get('duration', 0))
    except (TypeError, ValueError):
        value = 0
    return value if math.isfinite(value) and value > 0 else None



def get_ffprobe_info(file_path):
    result = subprocess.run([executable('ffprobe'), '-v', 'quiet', '-print_format', 'json',
        '-show_format', '-show_streams', str(file_path)], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise FFmpegError(result.stderr or 'ffprobe could not read this media')
    return json.loads(result.stdout)


def extract_audio(video_path, output_audio_path, checkpoint=lambda: None):
    run_ffmpeg(['-i', video_path, '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', output_audio_path], checkpoint)


def embed_subtitles(video_path, srt_path, output_video_path, checkpoint=lambda: None, subtitle_lang='ar', progress=None):
    # MKV supports copied media codecs and a selectable UTF-8 SRT track.
    run_ffmpeg(['-i', video_path, '-i', srt_path, '-map', '0:v:0', '-map', '0:a?', '-map', '1:0',
        '-c', 'copy', '-c:s', 'mov_text' if Path(output_video_path).suffix.lower() == '.mp4' else 'srt', '-metadata:s:s:0', 'language=' + {'ar': 'ara', 'en': 'eng', 'tr': 'tur', 'ko': 'kor'}[subtitle_lang], output_video_path], checkpoint, duration=media_duration(video_path), progress=progress)


def burn_subtitles(video_path, srt_path, output_video_path, checkpoint=lambda: None, progress=None):
    # Only a fixed basename enters the filter syntax. Apostrophes, colons and
    # brackets in user paths cannot change the FFmpeg filter expression.
    with tempfile.TemporaryDirectory(prefix='veyora-burn-') as temp:
        shutil.copyfile(srt_path, Path(temp) / 'captions.srt')
        run_ffmpeg(['-threads', '2', '-filter_threads', '1', '-i', Path(video_path).resolve(), '-vf',
            "subtitles=captions.srt:force_style='FontName=Arial,FontSize=20'",
            '-c:v', 'libx264', '-crf', '20', '-preset', 'veryfast', '-threads', '2',
            '-x264-params', 'rc-lookahead=4:sync-lookahead=0:ref=2', '-c:a', 'aac',
            Path(output_video_path).resolve()], checkpoint, cwd=temp, duration=media_duration(video_path), progress=progress)
