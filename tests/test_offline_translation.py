"""Real-model tests are opt-in via VEYORA_AR_MODEL_ARCHIVE; no online translation."""
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from translator.exceptions import TranslationError
from translator import offline_model, translation_provider, pipeline
from translator.translation_provider import TranslatorProvider


def test_checksum_rejects_corrupt_archive(tmp_path):
    archive = tmp_path / 'bad.argosmodel'
    archive.write_bytes(b'not a verified model')
    with pytest.raises(TranslationError, match='checksum'):
        offline_model._extract_verified(archive, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_cancel_before_model_network(monkeypatch):
    network = Mock(side_effect=AssertionError('Unexpected network'))
    monkeypatch.setattr(offline_model.requests, 'get', network)
    def cancel():
        raise RuntimeError('Cancelled by user')
    with pytest.raises(RuntimeError, match='Cancelled'):
        offline_model.ensure_model(checkpoint=cancel)
    network.assert_not_called()


def test_offline_provider_cache_chunking_and_cancel(monkeypatch):
    tokenizer = Mock()
    tokenizer.encode.return_value = ['word'] * 350
    tokenizer.decode.return_value = 'مرحبا'
    translator = Mock()
    translator.translate_batch.return_value = [SimpleNamespace(hypotheses=[['arabic']])]
    monkeypatch.setattr(translation_provider, '_runtimes', {('en', 'ar'): (tokenizer, translator)})
    provider = TranslatorProvider()
    assert provider.translate('long text') == 'مرحبا مرحبا مرحبا'
    assert provider.translate('long text') == 'مرحبا مرحبا مرحبا'
    assert translator.translate_batch.call_count == 3
    def cancel():
        raise RuntimeError('Cancelled')
    with pytest.raises(RuntimeError):
        provider.translate('long text', checkpoint=cancel)


def test_english_transcript_survives_translation_setup_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(offline_model, 'config_root', lambda: tmp_path / 'config')
    monkeypatch.setattr(pipeline, 'config_root', lambda: tmp_path / 'config')
    media = tmp_path / 'movie.mp4'
    media.write_bytes(b'unchanged media')
    monkeypatch.setattr(pipeline, 'extract_audio', lambda *a: None)
    transcriber = Mock()
    transcriber.transcribe.return_value = ([SimpleNamespace(start=0, end=1, text='Hello world')], None)
    monkeypatch.setattr(pipeline, 'Transcriber', lambda **kwargs: transcriber)
    provider = Mock()
    provider.prepare.side_effect = TranslationError('Model download unavailable')
    monkeypatch.setattr(pipeline, 'TranslatorProvider', lambda *args: provider)
    with pytest.raises(TranslationError):
        pipeline.TranslationPipeline(media, tmp_path).run(enhance_speech=False)
    assert list(tmp_path.glob('*.en.srt'))
    provider.prepare.side_effect = None
    provider.translate.return_value = 'مرحبا بالعالم'
    events = []
    output = pipeline.TranslationPipeline(media, tmp_path).run(enhance_speech=False,progress=lambda *args: events.append(args))
    assert transcriber.transcribe.call_count == 1  # retry reuses the durable English transcript
    assert 'مرحبا' in Path(output['subtitle']).read_text(encoding='utf-8')
    assert any('saved English transcript' in text for text, _ in events)
    assert media.read_bytes() == b'unchanged media'


@pytest.mark.parametrize('source,target,archive_variable,samples', [
    ('en', 'ar', 'VEYORA_AR_MODEL_ARCHIVE', ['Hello world.', 'This video explains how to manage your nightclub in the game.']),
    ('ar', 'en', 'VEYORA_AR_EN_MODEL_ARCHIVE', ['مرحبا بالعالم', 'هذا الفيديو يشرح كيفية تحميل الملفات وترجمتها.', 'يمكنك شراء سيارة جديدة وتوفير المال.']),
])
def test_real_bidirectional_models_no_translation_network(monkeypatch, tmp_path, source, target, archive_variable, samples):
    if not os.environ.get(archive_variable):
        pytest.skip('Set ' + archive_variable + ' to run actual model integration')
    monkeypatch.setattr(offline_model, 'config_root', lambda: tmp_path)
    monkeypatch.setattr(translation_provider, '_runtimes', {})
    network = Mock(side_effect=AssertionError('Offline inference must not call network'))
    monkeypatch.setattr(offline_model.requests, 'get', network)
    provider = TranslatorProvider(source, target)
    provider.prepare()
    for text in samples:
        value = provider.translate(text)
        print(f'ACTUAL OFFLINE {source}->{target}: {text} => {value}')
        if target == 'ar':
            assert any('\u0600' <= c <= '\u06ff' for c in value)
        else:
            assert __import__('re').search('[A-Za-z]', value)
        assert value != text
    network.assert_not_called()
    assert offline_model.is_installed(offline_model.model_directory(source, target), source, target)


def test_real_whisper_audio_decode_no_metadata_errors(tmp_path):
    import wave
    from faster_whisper.audio import decode_audio
    path = tmp_path / 'audio.wav'
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b'\x00\x00' * 16000)
    assert len(decode_audio(str(path))) == 16000


def test_transcript_cache_isolated_by_source_language(tmp_path):
    path = tmp_path / 'same.mp4'
    path.write_bytes(b'same media')
    assert pipeline._cache_key(path, lambda: None, 'en') != pipeline._cache_key(path, lambda: None, 'ar')


def test_multilingual_speech_model_selection(monkeypatch):
    # This is a factory-selection unit test, not native ONNX inference.
    # Avoid native telemetry/session initialization in a mocked test.
    import sys
    telemetry = Mock()
    monkeypatch.setitem(sys.modules, 'onnxruntime', SimpleNamespace(disable_telemetry_events=telemetry))
    import faster_whisper
    import translator.transcription as transcription
    monkeypatch.setattr(transcription, '_model', None)
    monkeypatch.setattr(transcription, '_model_key', None)
    model = Mock()
    model.transcribe.side_effect = [([SimpleNamespace(start=0, end=1, text='مرحبا')], SimpleNamespace(duration=1)),
                                  ([SimpleNamespace(start=0, end=1, text='Hello')], SimpleNamespace(duration=1))]
    factory = Mock(return_value=model)
    monkeypatch.setattr(faster_whisper, 'WhisperModel', factory)
    transcription.Transcriber(language='ar').transcribe('example.wav')
    assert factory.call_args.args[0] == 'base'
    assert model.transcribe.call_args.kwargs['language'] == 'ar'
    assert model.transcribe.call_args.kwargs['task'] == 'transcribe'
    transcription.Transcriber(language='en').transcribe('example.wav')
    assert factory.call_args.args[0] == 'base.en'
    assert model.transcribe.call_args.kwargs['language'] == 'en'
    assert factory.call_count == 2
    assert telemetry.call_count == 2


def test_unsupported_pair_rejected():
    with pytest.raises(TranslationError, match='Supported translation directions'):
        TranslatorProvider('fr', 'ar')


@pytest.mark.skipif(not os.environ.get('VEYORA_AR_EN_MODEL_ARCHIVE'), reason='Reverse model archive required for real integration')
def test_real_reverse_pipeline_english_subtitle_track(monkeypatch, tmp_path):
    from translator.video_renderer import run_ffmpeg, get_ffprobe_info
    monkeypatch.setattr(offline_model, 'config_root', lambda: tmp_path / 'config')
    monkeypatch.setattr(pipeline, 'config_root', lambda: tmp_path / 'config')
    monkeypatch.setattr(translation_provider, '_runtimes', {})
    network = Mock(side_effect=AssertionError('No translation network'))
    monkeypatch.setattr(offline_model.requests, 'get', network)
    media = tmp_path / 'arabic-source.mp4'
    run_ffmpeg(['-f', 'lavfi', '-i', 'color=c=blue:s=320x240:d=1', '-f', 'lavfi', '-i',
                'sine=frequency=440:duration=1', '-c:v', 'libx264', '-c:a', 'aac', '-shortest', media])
    transcriber = Mock()
    transcriber.transcribe.return_value = ([SimpleNamespace(start=0, end=.9, text='مرحبا بالعالم')], None)
    factory = Mock(return_value=transcriber)
    monkeypatch.setattr(pipeline, 'Transcriber', factory)
    result = pipeline.TranslationPipeline(media, tmp_path).run(mode='embed', source_lang='ar', target_lang='en')
    factory.assert_called_once_with(language='ar')
    assert Path(result['source_subtitle']).suffixes[-2:] == ['.ar', '.srt']
    assert Path(result['subtitle']).suffixes[-2:] == ['.en', '.srt']
    assert 'مرحبا' in Path(result['source_subtitle']).read_text(encoding='utf-8')
    assert __import__('re').search('[A-Za-z]', Path(result['subtitle']).read_text(encoding='utf-8'))
    streams = get_ffprobe_info(result['video'])['streams']
    assert any(s['codec_type'] == 'subtitle' and s['tags']['language'] == 'eng' for s in streams)
    assert media.is_file()
    network.assert_not_called()
