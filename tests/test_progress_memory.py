import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from translator import video_renderer as renderer
from translator.resources import processing_slot


def test_progress_microseconds_eta_and_na():
    fraction, eta, speed = renderer._progress_values({'out_time_us': '2500000', 'speed': '0.5x'}, 10, 5)
    assert fraction == .25 and eta == 15 and speed == .5
    assert renderer._progress_values({'out_time_us': 'N/A', 'speed': 'N/A'}, None, .1) == (None, None, None)
    fraction, eta, speed = renderer._progress_values({'out_time': '00:00:03.000', 'speed': 'N/A'}, 10, 2)
    assert fraction == .3 and speed == 1.5 and eta == pytest.approx(7/1.5)


def test_real_ffmpeg_progress_between_zero_and_completion(tmp_path):
    events = []
    output = tmp_path / 'progress.mp4'
    renderer.run_ffmpeg(['-re', '-f', 'lavfi', '-i', 'color=c=blue:s=320x240:r=20:d=2',
        '-c:v', 'libx264', '-threads', '2', output], duration=2,
        progress=lambda *args: events.append(args))
    assert output.is_file()
    assert events[-1][0] == 1 and events[-1][1] == 0
    assert any(x is not None and 0 < x < 1 for x, _, _ in events[:-1])
    assert any(eta is not None and eta > 0 for _, eta, _ in events[:-1])
    known = [x for x, _, _ in events if x is not None]
    assert known == sorted(known)


def test_failed_encode_does_not_claim_completion(tmp_path):
    events = []
    from translator.exceptions import FFmpegError
    with pytest.raises(FFmpegError):
        renderer.run_ffmpeg(['-i', tmp_path / 'missing.mp4', tmp_path / 'no.mp4'], duration=10,
                            progress=lambda *args: events.append(args))
    assert not any(x == 1 for x, _, _ in events)


def test_processing_gate_blocks_and_can_cancel_waiting_thread():
    ready, done = threading.Event(), threading.Event()
    messages = []
    errors = []
    def waiter():
        def cancel():
            ready.set()
            raise RuntimeError('Cancelled while waiting')
        try:
            with processing_slot(cancel, lambda *args: messages.append(args)):
                errors.append('Must not enter')
        except RuntimeError as exc:
            errors.append(str(exc))
        finally:
            done.set()
    with processing_slot():
        thread = threading.Thread(target=waiter)
        thread.start()
        assert ready.wait(2) and done.wait(2)
    thread.join()
    assert errors == ['Cancelled while waiting']
    assert 'Waiting' in messages[0][0]
    with processing_slot():
        pass  # cancellation of another waiter did not leak/release this lock


def test_release_translation_models_unloads_native_weights(monkeypatch):
    from translator import translation_provider as provider
    model = Mock()
    runtimes = {('en', 'ar'): (Mock(), model)}
    monkeypatch.setattr(provider, '_runtimes', runtimes)
    provider.release_translation_models()
    model.unload_model.assert_called_once_with()
    assert runtimes == {}


def test_release_speech_model_unloads_and_resets(monkeypatch):
    from translator import transcription
    model = Mock()
    monkeypatch.setattr(transcription, '_model', model)
    monkeypatch.setattr(transcription, '_model_key', ('base.en', 'cpu'))
    transcription.release_speech_model()
    model.model.unload_model.assert_called_once_with()
    assert transcription._model is None and transcription._model_key is None


def test_burn_uses_bounded_decoder_encoder_and_lookahead(monkeypatch, tmp_path):
    subtitle = tmp_path / 'source.srt'
    subtitle.write_text('1\n00:00:00,000 --> 00:00:01,000\nمرحبا\n', encoding='utf-8')
    run = Mock()
    monkeypatch.setattr(renderer, 'run_ffmpeg', run)
    monkeypatch.setattr(renderer, 'media_duration', lambda _: 10)
    renderer.burn_subtitles(tmp_path / 'source.mp4', subtitle, tmp_path / 'output.mp4')
    args = run.call_args.args[0]
    positions = [i for i, v in enumerate(args) if v == '-threads']
    assert len(positions) == 2 and all(args[i + 1] == '2' for i in positions)
    assert args[args.index('-preset') + 1] == 'veryfast'
    assert 'rc-lookahead=4:sync-lookahead=0:ref=2' in args
    assert '-s' not in args and '-r' not in args  # no resolution/frame-rate reduction


def test_pipeline_releases_models_before_render_and_forwards_eta(monkeypatch, tmp_path):
    from translator import pipeline
    media = tmp_path / 'movie.mp4'
    media.write_bytes(b'media for lifecycle test')
    monkeypatch.setattr(pipeline, 'config_root', lambda: tmp_path / 'config')
    monkeypatch.setattr(pipeline, 'extract_audio', lambda *args: None)
    recognizer = Mock()
    recognizer.transcribe.return_value = ([SimpleNamespace(start=0, end=1, text='Hello')], None)
    monkeypatch.setattr(pipeline, 'Transcriber', lambda **kwargs: recognizer)
    provider = Mock()
    provider.translate.return_value = 'مرحبا'
    monkeypatch.setattr(pipeline, 'TranslatorProvider', lambda *args: provider)
    lifecycle, events = [], []
    monkeypatch.setattr(pipeline, 'release_speech_model', lambda: lifecycle.append('speech released'))
    monkeypatch.setattr(pipeline, 'release_translation_models', lambda: lifecycle.append('translation released'))
    def render(source, subtitle, output, checkpoint, progress):
        assert lifecycle[:2] == ['speech released', 'translation released']
        lifecycle.append('render started')
        progress(.5, 90, .8)
        Path(output).write_bytes(b'rendered video')
    monkeypatch.setattr(pipeline, 'burn_subtitles', render)
    result = pipeline.TranslationPipeline(media, tmp_path).run(mode='burn', progress=lambda *args: events.append(args))
    assert Path(result['video']).read_bytes() == b'rendered video'
    assert any('50.0%' in text and '00:01:30' in text and '0.80x' in text and value == .5 for text, value in events)
