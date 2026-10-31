"""Extra acceptance checks for reported translation coverage and large queues.

These tests use synthetic signals/data and do not claim to validate the actual
Another Love music recording or full fidelity of offline translation models.
"""
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_transcript_tail_requiring_review_is_not_claimed_as_fully_translated(monkeypatch, tmp_path):
    """Issue 1/2: absent trailing speech cues must be reported, not invented."""
    from translator import pipeline, automatic_audio

    recognized = [SimpleNamespace(start=0.0, end=141.0, text="Recognized early section")]
    class Recognizer:
        def __init__(self, language):
            assert language == "en"
        def transcribe(self, *args, **kwargs):
            return list(recognized), SimpleNamespace(language="en")

    monkeypatch.setattr(pipeline, "Transcriber", Recognizer)
    monkeypatch.setattr(
        automatic_audio, "audio_activity",
        lambda _audio: {"duration": 247.0, "active_seconds": list(range(144, 247))},
    )
    monkeypatch.setattr(automatic_audio, "needs_candidate", lambda *_args: False)

    processor = pipeline.TranslationPipeline(tmp_path / "video.mp4", tmp_path / "out")
    processor.speech_policy = "auto"
    processor.coverage_review = None
    actual, info = processor._recognize(
        tmp_path / "synthetic.wav", "en", lambda: None, lambda *_args: None,
    )

    assert len(actual) == 1 and actual[0].end == 141.0
    assert info.language == "en"
    assert processor.coverage_review["status"] == "REVIEW REQUIRED"
    assert processor.coverage_review["last_recognized_end"] == 141.0
    assert processor.coverage_review["audio_duration"] == 247.0
    assert processor.coverage_review["enhancement_attempted"] is False


def test_short_silent_tail_does_not_trigger_false_incomplete_transcript(monkeypatch, tmp_path):
    """Issue 1: a short ending is not sufficient evidence of missing words."""
    from translator import pipeline, automatic_audio

    class Recognizer:
        def __init__(self, language):
            pass
        def transcribe(self, *args, **kwargs):
            return [SimpleNamespace(start=0.0, end=28.0, text="End of talk")], SimpleNamespace(language="en")

    monkeypatch.setattr(pipeline, "Transcriber", Recognizer)
    monkeypatch.setattr(automatic_audio, "audio_activity", lambda _: {
        "duration": 30.0, "active_seconds": list(range(0, 28))
    })
    monkeypatch.setattr(automatic_audio, "needs_candidate", lambda *_args: False)

    processor = pipeline.TranslationPipeline(tmp_path / "video.mp4", tmp_path / "out")
    processor.speech_policy = "auto"
    processor.coverage_review = None
    actual, _ = processor._recognize(
        tmp_path / "synthetic.wav", "en", lambda: None, lambda *_args: None,
    )
    assert len(actual) == 1
    assert processor.coverage_review is None


def test_pause_all_blocks_newly_queued_tasks_until_resume():
    """Additional issue: global pause must also stop tasks added while paused."""
    from main import DownloadQueueManager

    manager = object.__new__(DownloadQueueManager)
    manager.lock = threading.RLock()
    manager.closed = False
    manager._all_paused = True
    manager.max_concurrent = 3
    manager.task_order = ["queued"]
    manager.tasks = {"queued": {"status": "Queued"}}
    manager.futures = {}
    manager.executor = Mock()
    future = Mock()
    manager.executor.submit.return_value = future
    manager._run_task = Mock()
    manager._notify_ui = Mock()

    manager._process_queue()
    manager.executor.submit.assert_not_called()
    assert manager.tasks["queued"]["status"] == "Queued"

    manager._all_paused = False
    manager._process_queue()
    manager.executor.submit.assert_called_once()
    assert manager.tasks["queued"]["status"] == "Downloading"
    future.add_done_callback.assert_called_once()


def test_many_mixed_download_cards_remain_renderable(monkeypatch):
    """Issues 6/7 + bulk queue: redraw real cards, including failed Arabic messages."""
    import main
    from desktop_ui import DesktopApp

    monkeypatch.setitem(main.DEFAULT_SETTINGS, "auto_update_check", False)
    app = DesktopApp()
    try:
        app.show_tab("Downloads")
        tasks = []
        for i in range(24):
            status = ("Failed", "Completed", "Downloading", "Paused")[i % 4]
            tasks.append({
                "id": f"acceptance-{i}",
                "url": f"https://example.com/{i}",
                "title": f"فيديو اختبار رقم {i}",
                "settings": {"quality": "1080p", "format": "MP4", "download_subs": False},
                "status": status,
                "progress": 1.0 if status == "Completed" else 0.2,
                "filesize": 1024 * 1024,
                "speed": "1 MB/s",
                "eta": "0:30",
                "error": "تحقق من بداية القص ونهايته" if status == "Failed" else None,
                "thumbnail": None,
            })

        monkeypatch.setattr(app.queue_manager, "get_tasks_by_status", lambda status_filter=None: tasks)
        for _ in range(3):
            app.render_download_items()
            app.update_idletasks()

        assert len(app.card_widgets) == 24
        assert len(app._card_info_labels) == 24
        for index, task in enumerate(tasks):
            if task["status"] == "Failed":
                assert app._card_info_labels[task["id"]].cget("text") == task["error"]
                assert app._card_buttons[task["id"]]["errorlog"].winfo_manager() == "pack"
            assert app.card_widgets[task["id"]].winfo_exists()
    finally:
        app._on_close()
