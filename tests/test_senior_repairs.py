import multiprocessing
import os
from pathlib import Path
import queue
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from runtime_support import LatestProgress, friendly_error
from translator import offline_model, pipeline, translation_provider, video_renderer
from translator.subtitle_generator import generate_srt, parse_srt
from translator.worker import run_translation


def test_progress_flood_is_bounded_and_delivered_on_consumer_thread():
    callbacks, events = queue.Queue(), []
    progress = LatestProgress(callbacks, lambda *a: events.append((threading.get_ident(), a)))
    producer = threading.Thread(target=lambda: [progress(str(i), i / 10000) for i in range(10000)])
    producer.start()
    producer.join()
    assert callbacks.qsize() == 1
    callbacks.get_nowait()()
    assert events == [(threading.get_ident(), ('9999', .9999))]
    progress('Saved', 1)
    callbacks.get_nowait()()
    assert events[-1][1] == ('Saved', 1)


def test_friendly_connection_error_is_logged_but_not_displayed(tmp_path, monkeypatch):
    monkeypatch.setenv('VEYORA_CONFIG_DIR', str(tmp_path))
    message = friendly_error(RuntimeError('ConnectError: [Errno 11001] getaddrinfo failed'), arabic=True)
    assert 'الإنترنت' in message
    assert 'getaddrinfo' not in message
    assert friendly_error(RuntimeError('technical detail'), cancelled=True) == 'Task cancelled.'


def test_corrupt_model_marker_is_treated_as_incomplete(tmp_path):
    for name in offline_model.REQUIRED:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'model')
    (tmp_path / 'VERIFIED_SHA256').write_bytes(b'\xff')
    assert not offline_model.is_installed(tmp_path)


def test_incomplete_model_is_preserved_and_replaced(monkeypatch, tmp_path):
    monkeypatch.setattr(offline_model, 'config_root', lambda: tmp_path)
    target = offline_model.model_directory()
    target.mkdir(parents=True)
    (target / 'partial-model').write_bytes(b'preserve')
    archive = tmp_path / 'archive'
    archive.write_bytes(b'test archive')
    monkeypatch.setenv('VEYORA_AR_MODEL_ARCHIVE', str(archive))
    def extract(_, destination, *args):
        for name in offline_model.REQUIRED:
            file = destination / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'verified content')
        (destination / 'VERIFIED_SHA256').write_text(offline_model.MODEL_SHA256)
    monkeypatch.setattr(offline_model, '_extract_verified', extract)
    assert offline_model.ensure_model() == target
    assert offline_model.is_installed(target)
    assert next(target.parent.glob('*.incomplete-*')).joinpath('partial-model').read_bytes() == b'preserve'


def test_model_mirror_uses_a_different_host(monkeypatch, tmp_path):
    import requests
    monkeypatch.setattr(offline_model, 'config_root', lambda: tmp_path)
    get = Mock(side_effect=requests.ConnectionError('offline'))
    monkeypatch.setattr(offline_model.requests, 'get', get)
    with pytest.raises(Exception, match='Could not download'):
        offline_model.ensure_model(source_lang='en', target_lang='tr')
    urls = [call.args[0] for call in get.call_args_list]
    assert len(set(urls)) == 2
    assert urls[0].endswith('translate-en_tr-1_5.argosmodel')
    assert urls[1].startswith('https://argos-net.com/')


def test_pivot_does_not_unload_models_for_every_cue(monkeypatch):
    unload = Mock()
    monkeypatch.setattr(translation_provider, 'release_translation_models', unload)
    provider = translation_provider.TranslatorProvider('ar', 'ko')
    for stage in provider.stages:
        stage.translate = Mock(side_effect=lambda text, **kw: text + ' translated')
    for _ in range(10):
        assert provider.translate('hello').endswith('translated translated')
    unload.assert_not_called()


def test_translation_duplicate_cache_is_bounded(monkeypatch):
    tokenizer, translator = Mock(), Mock()
    tokenizer.encode.return_value = ['token']
    tokenizer.decode.return_value = 'مرحبا'
    translator.translate_batch.return_value = [SimpleNamespace(hypotheses=[['translated']])]
    monkeypatch.setattr(translation_provider, '_runtimes', {('en', 'ar'): (tokenizer, translator)})
    provider = translation_provider.DirectTranslatorProvider()
    for i in range(1000):
        provider.translate(str(i))
    assert len(provider.cache) == 256


def test_cancelled_publish_does_not_leave_partial_final_file(tmp_path):
    source, destination = tmp_path / 'source', tmp_path / 'final.mp4'
    source.write_bytes(b'x' * (3 * 1024 * 1024))
    calls = 0
    def cancel():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError('Cancelled')
    with pytest.raises(RuntimeError, match='Cancelled'):
        pipeline._publish_file(source, destination, cancel)
    assert not destination.exists()
    assert not list(tmp_path.glob('*.partial'))
    assert source.stat().st_size == 3 * 1024 * 1024


def test_bad_srt_does_not_replace_existing_output(tmp_path):
    destination = tmp_path / 'عنوان.srt'
    destination.write_text('original', encoding='utf8')
    with pytest.raises(ValueError):
        generate_srt([SimpleNamespace(start=2, end=1, text='invalid')], destination)
    assert destination.read_text(encoding='utf8') == 'original'
    assert not list(tmp_path.glob('*.partial'))


def test_actual_mp4_selectable_subtitles_arabic_filename(tmp_path):
    video = tmp_path / 'فيديو عربي.mp4'
    video_renderer.run_ffmpeg(['-f', 'lavfi', '-i', 'color=s=160x90:d=1',
                              '-c:v', 'libx264', video])
    srt = tmp_path / 'ترجمة.srt'
    generate_srt([SimpleNamespace(start=0, end=.9, text='مرحبا بالعالم')], srt)
    output = tmp_path / 'نتيجة.mp4'
    video_renderer.embed_subtitles(video, srt, output)
    streams = video_renderer.get_ffprobe_info(output)['streams']
    assert any(s['codec_name'] == 'mov_text' and s['tags']['language'] == 'ara' for s in streams)


def test_actual_spawned_translation_and_worker_cleanup(tmp_path):
    source = tmp_path / 'ترجمة أصلية.srt'
    generate_srt([SimpleNamespace(start=1, end=2, text='مرحبا بالعالم')], source)
    result = run_translation(source, tmp_path / 'output', source_lang='ar', target_lang='ar')
    cues = parse_srt(result['subtitle'])
    assert cues[0].text == 'مرحبا بالعالم' and cues[0].start == 1
    assert not any(c.name == 'veyora-translation' for c in multiprocessing.active_children())


def test_spawned_translation_cancel_stops_worker(tmp_path):
    source = tmp_path / 'large.srt'
    source.write_text('1\n00:00:00,000 --> 00:00:01,000\nHello\n\n' * 100000, encoding='utf8')
    started = time.monotonic()
    def checkpoint():
        if time.monotonic() - started > .2:
            raise RuntimeError('Cancelled')
    with pytest.raises(RuntimeError, match='Cancelled'):
        run_translation(source, tmp_path / 'output', source_lang='en', target_lang='ar', checkpoint=checkpoint)
    assert time.monotonic() - started < 8
    assert not any(c.name == 'veyora-translation' for c in multiprocessing.active_children())


def test_force_stop_unresponsive_process():
    from translator.worker import _stop
    process = multiprocessing.get_context('spawn').Process(target=time.sleep, args=(60,))
    process.start()
    try:
        _stop(process)
        assert not process.is_alive()
    finally:
        if process.is_alive():
            process.kill()
            process.join()
        process.close()


def test_stalled_ffmpeg_process_is_stopped(monkeypatch):
    import subprocess
    import sys
    from translator.exceptions import FFmpegError
    original = subprocess.Popen
    processes = []
    def launch(*args, **kwargs):
        process = original([sys.executable, '-c', 'import time; time.sleep(60)'], **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(video_renderer.subprocess, 'Popen', launch)
    with pytest.raises(FFmpegError, match='stopped making progress'):
        video_renderer.run_ffmpeg([], stall_timeout=.2)
    assert len(processes) == 1 and processes[0].poll() is not None
    assert processes[0].stdout.closed


def test_actual_ffmpeg_cancel_after_start(monkeypatch, tmp_path):
    import subprocess
    original, processes = subprocess.Popen, []
    def launch(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(video_renderer.subprocess, 'Popen', launch)
    start = time.monotonic()
    def cancel():
        if time.monotonic() - start > .4:
            raise RuntimeError('Cancelled by user')
    with pytest.raises(RuntimeError, match='Cancelled'):
        video_renderer.run_ffmpeg(['-re', '-f', 'lavfi', '-i', 'color=s=160x90:d=30',
                                  '-c:v', 'libx264', tmp_path / 'cancelled.mp4'], checkpoint=cancel)
    assert processes and all(p.poll() is not None and p.stdout.closed for p in processes)


def test_side_translation_button_runs_and_ui_keeps_ticking(monkeypatch, tmp_path):
    import customtkinter as ctk
    import main
    from desktop_ui import DesktopApp
    monkeypatch.setitem(main.DEFAULT_SETTINGS, 'auto_update_check', False)
    app = DesktopApp()
    failures, ticks = [], []
    app.report_callback_exception = lambda *args: failures.append(str(args))
    monkeypatch.setattr(main.messagebox, 'showerror', lambda *a: failures.append(str(a)))
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    def heartbeat():
        ticks.append(time.monotonic())
        app.after(20, heartbeat)
    try:
        source = tmp_path / 'ترجمة محلية.srt'
        generate_srt([SimpleNamespace(start=1, end=2, text='مرحبا بالعالم')], source)
        app.selected_folder = str(tmp_path / 'out')
        app.show_tab('Translation')
        widgets = list(descendants(app.pages.pages[app.active_tab]['host']))
        entry = next(w for w in widgets if isinstance(w, ctk.CTkEntry))
        entry.insert(0, str(source))
        menus = [w for w in widgets if isinstance(w, ctk.CTkOptionMenu)]
        menus[0].set(app._label_for_lang('ar', allow_auto=True))
        menus[1].set(app._label_for_lang('ar', allow_auto=False))
        start = next(w for w in widgets if isinstance(w, ctk.CTkButton)
                     and w.cget('text') == app.t('بدء المعالجة', 'Start processing'))
        app.after(20, heartbeat)
        start.invoke()
        assert app._local_running
        assert start.cget('state') == 'disabled'
        assert start.cget('text') == app.t('جارٍ المعالجة…', 'Processing…')
        deadline = time.monotonic() + 20
        while app._local_running and time.monotonic() < deadline:
            app.update()
            time.sleep(.01)
        assert not app._local_running
        assert not failures
        assert len(ticks) >= 3
        output = next((tmp_path / 'out').glob('*.srt'))
        assert parse_srt(output)[0].text == 'مرحبا بالعالم'
    finally:
        app._on_close()


def test_busy_feedback_cancel_and_navigation(monkeypatch, tmp_path):
    import customtkinter as ctk
    import main
    import translator.worker
    from desktop_ui import DesktopApp
    entered, calls = threading.Event(), []
    def slow_job(*args, checkpoint, progress, **kwargs):
        calls.append(args)
        entered.set()
        while True:
            checkpoint()
            time.sleep(.02)
    monkeypatch.setattr(translator.worker, 'run_translation', slow_job)
    monkeypatch.setitem(main.DEFAULT_SETTINGS, 'auto_update_check', False)
    app = DesktopApp()
    errors, ticks = [], []
    app.report_callback_exception = lambda *args: errors.append(str(args))
    monkeypatch.setattr(main.messagebox, 'showerror', lambda *a: errors.append(str(a)))
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    def tick():
        ticks.append(time.monotonic())
        app.after(20, tick)
    def local_buttons():
        return [w for w in descendants(app.pages.pages[app.active_tab]['host']) if isinstance(w, ctk.CTkButton)]
    def pump(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.update()
            time.sleep(.01)
    try:
        source = tmp_path / 'input.mp4'
        source.write_bytes(b'fixture; backend is controlled for UI regression')
        app.show_tab('Translation')
        entry = next(w for w in descendants(app.pages.pages[app.active_tab]['host']) if isinstance(w, ctk.CTkEntry))
        entry.insert(0, str(source))
        buttons = local_buttons()
        start = next(w for w in buttons if w.cget('text') == app.t('بدء المعالجة', 'Start processing'))
        cancel = next(w for w in buttons if w.cget('text') == app.t('إلغاء', 'Cancel'))
        assert cancel.cget('state') == 'disabled'
        app.after(20, tick)
        start.invoke()
        start.invoke()  # Repeated clicks must not submit another worker.
        assert start.cget('state') == 'disabled'
        pump(.4)
        assert entered.is_set() and len(calls) == 1
        app.iconify()
        pump(.2)
        app.deiconify()
        pump(.2)
        app.show_tab('Dashboard')
        app.show_tab('Translation')
        buttons = local_buttons()
        start = next(w for w in buttons if w.cget('text') == app.t('جارٍ المعالجة…', 'Processing…'))
        cancel = next(w for w in buttons if w.cget('text') == app.t('إلغاء', 'Cancel'))
        assert start.cget('state') == 'disabled'
        cancel.invoke()
        assert start.cget('text') == app.t('جارٍ الإلغاء…', 'Cancelling…')
        assert cancel.cget('state') == 'disabled'
        pump(.5)
        assert not app._local_running
        assert start.cget('state') == 'normal'
        assert cancel.cget('state') == 'disabled'
        assert not errors and len(ticks) > 5
    finally:
        app._on_close()


@pytest.mark.skipif(not os.environ.get('VEYORA_INTEGRATION_MODEL_DIR'), reason='Prepared local models required')
@pytest.mark.parametrize('source', ['ar', 'en', 'tr', 'ko'])
def test_real_three_target_translations_without_network(source, monkeypatch):
    root = Path(os.environ['VEYORA_INTEGRATION_MODEL_DIR'])
    monkeypatch.setenv('VEYORA_CONFIG_DIR', str(root))
    monkeypatch.setattr(offline_model, 'config_root', lambda: root)
    samples = {'ar': 'مرحبا بالعالم', 'en': 'Hello world.', 'tr': 'Merhaba dünya.', 'ko': '안녕하세요.'}
    network = Mock(side_effect=AssertionError('No network allowed during inference'))
    monkeypatch.setattr(offline_model.requests, 'get', network)
    import socket
    monkeypatch.setattr(socket.socket, 'connect', network)
    for target in samples:
        if target == source:
            continue
        try:
            provider = translation_provider.TranslatorProvider(source, target)
            provider.prepare()
            translated = provider.translate(samples[source])
            print(f'ACTUAL {source}->{target}: {translated}')
            assert translated.strip() and translated != samples[source]
            if target == 'ar':
                assert any('\u0600' <= c <= '\u06ff' for c in translated)
            elif target == 'ko':
                assert any('가' <= c <= '힣' for c in translated)
            else:
                assert any('a' <= c.lower() <= 'z' for c in translated)
        finally:
            translation_provider.release_translation_models()
    network.assert_not_called()
