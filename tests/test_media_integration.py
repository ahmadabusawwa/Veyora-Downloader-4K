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


def test_actual_download_cancel_resume_uses_range(tmp_path, monkeypatch):
    import time
    from yt_dlp import YoutubeDL
    from yt_dlp.extractor.common import InfoExtractor
    from translator.video_renderer import run_ffmpeg
    valid=tmp_path/'valid-resume.mp4'
    run_ffmpeg(['-f','lavfi','-i','testsrc2=s=640x360:r=15:d=4','-c:v','libx264','-crf','0','-preset','ultrafast','-threads','2',valid])
    payload = valid.read_bytes()
    ranges = []
    head_requests = []
    class Media(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_HEAD(self):
            # yt-dlp's Generic extractor probes content types before deciding
            # whether a URL can be downloaded directly.
            head_requests.append(self.path)
            self.send_response(200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()

        def do_GET(self):
            import re
            requested = self.headers.get('Range')
            start, end = 0, len(payload) - 1
            if requested:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
                if not match or not any(match.groups()):
                    self.send_error(416, 'Malformed byte range')
                    return
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), end) if last else end
                else:
                    start = max(0, len(payload) - int(last))
                if start > end or start >= len(payload):
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{len(payload)}')
                    self.end_headers()
                    return
            ranges.append(start)
            self.send_response(206 if requested else 200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Content-Length', str(end - start + 1))
            self.send_header('Accept-Ranges', 'bytes')
            if requested:
                self.send_header('Content-Range', f'bytes {start}-{end}/{len(payload)}')
            self.end_headers()
            try:
                for i in range(start, end + 1, 16384):
                    self.wfile.write(payload[i:min(i + 16384, end + 1)])
                    self.wfile.flush()
                    # Keep the actual file transfer slow enough to permit the
                    # application to pause before the network transfer finishes.
                    time.sleep(.02)
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Media)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # This test isolates the real yt-dlp HTTP/Range transport instead of
    # GenericIE's unrelated content-sniffing of a synthetic local website.
    # Only extractor metadata is synthetic; HTTP media bytes, .part files,
    # pause, cancel and byte-range resume all remain real.
    media_url = f'http://127.0.0.1:{server.server_port}/video.mp4'
    class LocalTransportFixtureIE(InfoExtractor):
        IE_NAME = 'Veyora:HTTPResumeFixture'
        _VALID_URL = r'https?://127[.]0[.]0[.]1:[0-9]+/fixture$'

        def _real_extract(self, url):
            return dict(id='authorized-resume', title='Authorized resume fixture',
                        url=media_url, ext='mp4')

    def real_http_downloader(options):
        downloader = YoutubeDL(options, auto_init=False)
        downloader.add_info_extractor(LocalTransportFixtureIE())
        downloader.add_default_info_extractors()
        return downloader

    monkeypatch.setattr(main, 'create_downloader', real_http_downloader)
    task = dict(id='resume', url=f'http://127.0.0.1:{server.server_port}/fixture', title='Test',
        settings={**main.DEFAULT_SETTINGS, 'download_subs': False, 'save_thumbnail': False,
                  'download_dir': str(tmp_path)})
    pause, cancel = threading.Event(), threading.Event()
    paused = threading.Event()
    result = []
    events = []
    def progress(tid, data):
        events.append((data.get('status'), data.get('downloaded_bytes'), data.get('total_bytes')))
        if data.get('downloaded_bytes', 0) > 65536:
            pause.set()
            paused.set()
    thread = threading.Thread(target=main.DownloadEngine.download_task,
        args=(task, progress, lambda *a: result.append(a), pause, cancel, str(tmp_path)))
    try:
        thread.start()
        assert paused.wait(10), {'result': result, 'ranges': list(ranges), 'head_requests': list(head_requests), 'events': events[-30:], 'alive': thread.is_alive(), 'part_files': [(p.name,p.stat().st_size) for p in tmp_path.glob('*.part')]}
        time.sleep(.15)
        assert thread.is_alive() and not result
        cancel.set()  # cancelling a paused worker must unblock it
        thread.join(10)
        assert not thread.is_alive() and result[0][1] is False
        parts = list(tmp_path.glob('*.part'))
        assert parts and 0 < parts[0].stat().st_size < len(payload)
        pause.clear()
        cancel.clear()
        requests_before_resume = len(ranges)
        resumed = []
        main.DownloadEngine.download_task(task, lambda *_: None, lambda *a: resumed.append(a),
            pause, cancel, str(tmp_path))
        assert resumed[0][1], resumed
        assert Path(task['downloaded_file']).read_bytes() == payload
        assert any(start > 0 for start in ranges[requests_before_resume:]), ranges
    finally:
        cancel.set()
        thread.join(10)
        server.shutdown()
        server.server_close()
