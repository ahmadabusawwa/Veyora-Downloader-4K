import ast
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import main
from translator.subtitle_generator import format_timestamp
from translator.translation_provider import TranslatorProvider
from translator.pipeline import TranslationPipeline


def wait_for(predicate, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.01)
    assert predicate(), 'Timed out'


def test_timestamps_rounding():
    assert format_timestamp(59.9999) == '00:01:00,000'
    assert format_timestamp(3600.001) == '01:00:00,001'
    with pytest.raises(ValueError):
        format_timestamp(-1)


def test_translation_direction_choices_all_handlers():
    assert main.selected_subtitle_language('Auto-Translate: English -> Arabic') == 'auto-ar'
    assert main.selected_subtitle_language('Auto-Translate: Arabic -> English') == 'auto-en'
    assert main.selected_subtitle_language('English (en)') == 'en'
    assert main.TRANSLATION_DIRECTIONS['auto-en'] == ('ar', 'en')
    source = Path(main.__file__).read_text(encoding='utf-8')
    assert source.count("task_settings['sub_lang'] = selected_subtitle_language(sub_lang_display)") == 4


def test_options_keep_resume_and_no_remote_template_injection(tmp_path):
    t = dict(id='x', url='https://example.com/v.mp4', video_id='../../evil/%(x)s',
             settings={**main.DEFAULT_SETTINGS, 'download_subs': False})
    options, _ = main.DownloadEngine.build_ydl_opts(t, Mock(), str(tmp_path))
    assert options['continuedl'] and not options['nopart'] and not options['overwrites']
    assert 'evil' not in options['outtmpl']
    assert options['nocheckcertificate'] is False


def test_queue_pause_cancel_retry_no_oversubscription(monkeypatch, tmp_path):
    calls = []
    def worker(task, progress, complete, pause, cancel, folder):
        calls.append(task['id'])
        while not cancel.wait(.01):
            if not pause.is_set():
                progress(task['id'], {'status': 'downloading', 'downloaded_bytes': 1, 'total_bytes': 10})
        complete(task['id'], False, 'Cancelled by user')
    monkeypatch.setattr(main.DownloadEngine, 'download_task', worker)
    callback = Mock()
    manager = main.DownloadQueueManager(callback, 1)
    settings = {**main.DEFAULT_SETTINGS, 'download_dir': str(tmp_path)}
    try:
        first = manager.add_task('https://example.com/a', settings)
        wait_for(lambda: len(calls) == 1)
        manager.pause_task(first)
        second = manager.add_task('https://example.com/b', settings)
        time.sleep(.05)
        assert len(calls) == 1
        assert manager.tasks[first]['status'] == 'Paused'
        assert manager.tasks[second]['status'] == 'Queued'
        manager.pause_task(second)
        manager.resume_task(second)
        assert manager.tasks[second]['status'] == 'Queued'
        assert not callback.called  # workers did not touch UI
        manager.poll_ui()
        callback.assert_called_once()
        manager.cancel_task(first)
        wait_for(lambda: len(calls) == 2)
        assert manager.tasks[first]['status'] == 'Cancelled'
        manager.retry_task(first)
        assert manager.tasks[first]['status'] == 'Queued'
        manager.cancel_task(second)
        wait_for(lambda: len(calls) == 3)
        manager.cancel_task(first)
        wait_for(lambda: not manager.futures)
    finally:
        manager.shutdown()
        manager.executor.shutdown(wait=True)


def test_worker_setup_errors_reach_completion(tmp_path):
    task = dict(id='x', url='https://example.com/x', settings={})
    callback = Mock()
    main.DownloadEngine.download_task(task, Mock(), callback, threading.Event(), threading.Event(), None)
    assert callback.call_args.args[1] is False



def test_pipeline_immutable_segments_unique_outputs(monkeypatch, tmp_path):
    from collections import namedtuple
    Segment = namedtuple('Segment', 'start end text')
    segment = Segment(0, 1, 'Hello')
    monkeypatch.setattr('translator.pipeline.extract_audio', lambda *a: None)
    transcriber = Mock()
    transcriber.transcribe.return_value = ([segment], None)
    monkeypatch.setattr('translator.pipeline.Transcriber', lambda **kwargs: transcriber)
    translator = Mock()
    translator.translate.return_value = 'مرحبا'
    monkeypatch.setattr('translator.pipeline.TranslatorProvider', lambda *args: translator)
    media = tmp_path / 'source.mp4'
    media.write_bytes(b'original')
    first = TranslationPipeline(media, tmp_path).run(enhance_speech=False)
    second = TranslationPipeline(media, tmp_path).run(enhance_speech=False)
    assert first['subtitle'] != second['subtitle']
    assert 'مرحبا' in Path(first['subtitle']).read_text(encoding='utf-8')
    assert segment.text == 'Hello' and media.read_bytes() == b'original'


class Widget:
    def __init__(self):
        self.destroy = Mock()
        self.configure = Mock()
        self.set = Mock()
        self.grid = Mock()
        self.grid_remove = Mock()
        self.pack = Mock()
        self.pack_forget = Mock()
    def winfo_exists(self):
        return True


def test_progress_updates_reuse_cards_and_buttons():
    task = dict(id='x', title='Test', status='Downloading', filesize=10, speed='1 MB/s', eta='0:01', progress=.1, error=None)
    manager = Mock(TERMINAL=main.DownloadQueueManager.TERMINAL)
    manager.get_tasks_by_status.return_value = [task]
    app = SimpleNamespace(queue_manager=manager, active_filter='all', card_widgets={},
        _card_progress_bars={}, _card_info_labels={}, _card_title_labels={},
        _card_buttons={}, _card_snapshots={}, status_label=Widget(), _empty_download_label=Widget())
    def create(t, index):
        app.card_widgets[t['id']] = Widget()
        app._card_progress_bars[t['id']] = Widget()
        app._card_info_labels[t['id']] = Widget()
        app._card_title_labels[t['id']] = Widget()
        app._card_buttons[t['id']] = {k: Widget() for k in ['pause', 'cancel']}
    app.create_download_card = Mock(side_effect=create)
    app._update_download_card = lambda t: main.VeyoraApp._update_download_card(app, t)
    main.VeyoraApp.render_download_items(app)
    card = app.card_widgets['x']
    buttons = app._card_buttons['x']
    for i in range(100):
        task['progress'] = i / 100
        main.VeyoraApp.render_download_items(app)
    app.create_download_card.assert_called_once()
    assert app.card_widgets['x'] is card
    card.destroy.assert_not_called()
    for button in buttons.values():
        assert button.pack.call_count == 1


def test_concurrent_history_atomic_and_no_lost_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'HISTORY_FILE', tmp_path / 'history.json')
    workers = [threading.Thread(target=main.HistoryManager.add, args=({'title': str(i)},)) for i in range(25)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert len(main.HistoryManager.load()) == 25


def test_real_segment_is_immutable_and_transcriber_does_not_mutate(monkeypatch):
    import translator.transcription as transcription
    from faster_whisper.transcribe import Segment
    segment = Segment(id=0, seek=0, start=0, end=1, text='Hello', tokens=[], avg_logprob=0,
                      compression_ratio=0, no_speech_prob=0, words=None, temperature=0)
    model = Mock()
    model.transcribe.return_value = (iter([segment]), None)
    monkeypatch.setattr(transcription, '_model', model)
    result, _ = transcription.Transcriber().transcribe('fake.wav')
    assert result == [segment]
    assert model.transcribe.call_args.kwargs['language'] == 'en'


