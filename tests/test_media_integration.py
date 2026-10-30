"""Local media integration: actual FFmpeg and actual yt-dlp, no external sites."""
import functools
import http.server
import threading
from pathlib import Path
from types import SimpleNamespace
import pytest
import main
from translator.subtitle_generator import generate_srt
from translator.video_renderer import run_ffmpeg, extract_audio, embed_subtitles, burn_subtitles, get_ffprobe_info


@pytest.fixture
def sample(tmp_path):
    media = tmp_path / "sample ' [x].mp4"
    run_ffmpeg(['-f', 'lavfi', '-i', 'color=c=blue:s=320x240:d=2',
                '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2',
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', media])
    return media


def test_actual_ffmpeg_arabic_track_and_burn(sample, tmp_path):
    subtitle = tmp_path / "captions ' [x].srt"
    generate_srt([SimpleNamespace(start=0, end=1.9, text='مرحبا بالعالم')], subtitle)
    audio = tmp_path / 'speech.wav'
    extract_audio(sample, audio)
    assert get_ffprobe_info(audio)['streams'][0]['sample_rate'] == '16000'
    muxed = tmp_path / 'muxed.mkv'
    embed_subtitles(sample, subtitle, muxed)
    streams = get_ffprobe_info(muxed)['streams']
    assert any(s['codec_type'] == 'subtitle' and s['tags']['language'] == 'ara' for s in streams)
    burned = tmp_path / 'burned.mp4'
    burn_subtitles(sample, subtitle, burned)
    streams = get_ffprobe_info(burned)['streams']
    assert any(s['codec_type'] == 'video' for s in streams)
    assert not any(s['codec_type'] == 'subtitle' for s in streams)
    assert sample.exists() and subtitle.exists()


def test_ffmpeg_cancellation(sample, tmp_path):
    def cancel():
        raise RuntimeError('Cancelled by user')
    with pytest.raises(RuntimeError, match='Cancelled'):
        extract_audio(sample, tmp_path / 'cancelled.wav', cancel)


def test_actual_ytdlp_http_download(sample, tmp_path):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    handler = functools.partial(Quiet, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    from urllib.parse import quote
    url = f'http://127.0.0.1:{server.server_port}/' + quote(sample.name)
    folder = tmp_path / 'downloads'
    task = dict(id='local', url=url, title='Local media', settings={**main.DEFAULT_SETTINGS,
                'download_subs': False, 'save_thumbnail': False, 'download_dir': str(folder)})
    result = []
    try:
        main.DownloadEngine.download_task(task, lambda *_: None, lambda *args: result.append(args),
            threading.Event(), threading.Event(), str(folder))
        assert result and result[0][1], result
        assert Path(task['downloaded_file']).is_file()
        assert Path(task['downloaded_file']).read_bytes() == sample.read_bytes()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_actual_download_cancel_resume_uses_range(tmp_path):
    import time
    from translator.video_renderer import run_ffmpeg
    valid=tmp_path/'valid-resume.mp4'
    run_ffmpeg(['-f','lavfi','-i','testsrc2=s=640x360:r=15:d=4','-c:v','libx264','-crf','0','-preset','ultrafast','-threads','2',valid])
    payload = valid.read_bytes()
    ranges = []
    class Media(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            start = int(self.headers.get('Range', 'bytes=0-').split('=')[1].split('-')[0])
            ranges.append(start)
            self.send_response(206 if start else 200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Content-Length', str(len(payload) - start))
            self.send_header('Accept-Ranges', 'bytes')
            if start:
                self.send_header('Content-Range', f'bytes {start}-{len(payload)-1}/{len(payload)}')
            self.end_headers()
            try:
                for i in range(start, len(payload), 16384):
                    self.wfile.write(payload[i:i + 16384])
                    self.wfile.flush()
                    time.sleep(.003)
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Media)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    task = dict(id='resume', url=f'http://127.0.0.1:{server.server_port}/video.mp4', title='Test',
        settings={**main.DEFAULT_SETTINGS, 'download_subs': False, 'save_thumbnail': False,
                  'download_dir': str(tmp_path)})
    pause, cancel = threading.Event(), threading.Event()
    paused = threading.Event()
    result = []
    def progress(tid, data):
        if data.get('downloaded_bytes', 0) > 65536:
            pause.set()
            paused.set()
    thread = threading.Thread(target=main.DownloadEngine.download_task,
        args=(task, progress, lambda *a: result.append(a), pause, cancel, str(tmp_path)))
    try:
        thread.start()
        assert paused.wait(10)
        time.sleep(.15)
        assert thread.is_alive() and not result
        cancel.set()  # cancelling a paused worker must unblock it
        thread.join(10)
        assert not thread.is_alive() and result[0][1] is False
        parts = list(tmp_path.glob('*.part'))
        assert parts and 0 < parts[0].stat().st_size < len(payload)
        pause.clear()
        cancel.clear()
        resumed = []
        main.DownloadEngine.download_task(task, lambda *_: None, lambda *a: resumed.append(a),
            pause, cancel, str(tmp_path))
        assert resumed[0][1], resumed
        assert Path(task['downloaded_file']).read_bytes() == payload
        assert any(start > 0 for start in ranges), ranges
    finally:
        cancel.set()
        thread.join(10)
        server.shutdown()
        server.server_close()
