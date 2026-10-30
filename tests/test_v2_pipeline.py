from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from translator import pipeline
from privacy import redact

@pytest.mark.parametrize('save_original',[False,True])
def test_final_only_and_original_opt_in(monkeypatch,tmp_path,save_original):
    media=tmp_path/'input.mp4';media.write_bytes(b'fixture')
    monkeypatch.setattr(pipeline,'config_root',lambda:tmp_path/'config')
    monkeypatch.setattr(pipeline,'extract_audio',lambda *a:None)
    transcriber=Mock();transcriber.transcribe.return_value=([SimpleNamespace(start=0,end=1,text='Hello')],None)
    monkeypatch.setattr(pipeline,'Transcriber',lambda **kw:transcriber)
    provider=Mock();provider.translate.return_value='مرحبا';monkeypatch.setattr(pipeline,'TranslatorProvider',lambda *a:provider)
    result=pipeline.TranslationPipeline(media,tmp_path/'out').run(save_original=save_original)
    assert Path(result['subtitle']).exists()
    assert ('source_subtitle' in result)==save_original
    assert bool(list((tmp_path/'out').glob('*.en.srt')))==save_original
    assert list((tmp_path/'config').rglob('*.json')) # transcript cache retained even when not exported

def test_srt_translation_uses_cues(monkeypatch,tmp_path):
    source=tmp_path/'input.srt';source.write_text('1\n00:00:01,000 --> 00:00:02,000\nHello\n',encoding='utf8')
    provider=Mock();provider.translate.return_value='مرحبا';monkeypatch.setattr(pipeline,'TranslatorProvider',lambda *a:provider)
    result=pipeline.TranslationPipeline(source,tmp_path/'out').run()
    assert 'مرحبا' in Path(result['subtitle']).read_text(encoding='utf8')
    assert '00:00:01,000 --> 00:00:02,000' in Path(result['subtitle']).read_text(encoding='utf8')

def test_diagnostic_redaction():
    text=redact('Failed https://user:secret@example.com/video?token=abc password=private')
    assert all(value not in text for value in ('secret','abc','private'))

def test_completed_filter_preserves_failed_jobs(monkeypatch,tmp_path):
    monkeypatch.setenv("VEYORA_CONFIG_DIR",str(tmp_path))
    import main
    manager=main.DownloadQueueManager(lambda:None,1)
    manager._process_queue=lambda:None
    try:
        completed=manager.add_task('https://example.com/1',dict(main.DEFAULT_SETTINGS))
        failed=manager.add_task('https://example.com/2',dict(main.DEFAULT_SETTINGS))
        manager.tasks[completed]['status']='Completed'
        manager.tasks[failed]['status']='Failed'
        assert [x['id'] for x in manager.get_tasks_by_status('completed')]==[completed]
        assert [x['id'] for x in manager.get_tasks_by_status('failed')]==[failed]
    finally:manager.shutdown()
