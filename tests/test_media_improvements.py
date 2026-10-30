from pathlib import Path
from types import SimpleNamespace as Segment
import threading


def test_public_drafts_exclude_signed_urls_credentials_and_fragments():
    from session_state import public_draft
    assert public_draft('https://www.youtube.com/watch?v=abc')
    for value in ['https://user:pass@example.com/v', 'https://example.com/v?token=abc','https://example.com/v#secret','https://example.com:8443/v']:
        assert public_draft(value) == ''


def test_recovery_journal_reopens_and_keeps_last_complete_transaction(tmp_path):
    from recovery_store import RecoveryStore
    path = tmp_path/'queue.db'
    store = RecoveryStore(path)
    store.submit([dict(id='one', status='Downloading', url='https://example.com/v')]);store.flush()
    assert RecoveryStore(path).load()[0]['id'] == 'one'
    store.submit([dict(id='two', status='Completed')]);store.flush()
    assert store.load() == [dict(id='two',status='Completed')]
    store.close()


def test_context_joins_fragments_without_losing_spring_or_timestamps():
    from translator.context_segments import sentence_groups
    groups = list(sentence_groups([Segment(start=0,end=2,text="But they won't flower"),Segment(start=2,end=4,text='like they did last spring.')]))
    assert len(groups)==1 and groups[0].text=="But they won't flower like they did last spring."
    assert (groups[0].start,groups[0].end)==(0,4)


def test_ass_style_is_resolution_relative_and_does_not_inject_overrides(tmp_path):
    from translator.subtitle_style import make_ass, normalize_style
    import pytest
    source=tmp_path/'s.srt';source.write_text('1\n00:00:00,000 --> 00:00:01,000\nمرحبا {\\pos(0,0)}\n',encoding='utf8')
    target=tmp_path/'s.ass';make_ass(source,target,1920,1080,dict(color='#FF0000',outline=.5,size_percent=3))
    value=target.read_text(encoding='utf-8-sig')
    assert 'Arial,32.4,&H000000FF' in value and '{\\pos' not in value
    with pytest.raises(ValueError): normalize_style(dict(color='red,FontSize=100'))


def test_conversion_formats_are_distinct_from_translation():
    from media_conversion import conversion_arguments
    assert 'pcm_s16le' in conversion_arguments('WAV',{})
    assert '-vn' in conversion_arguments('MP3',{})
    assert 'scale=-2:720' in conversion_arguments('MKV',dict(resolution='720'))
    import pytest
    with pytest.raises(ValueError): conversion_arguments('MP4',dict(codec='injected'))


def test_duplicate_download_and_explicit_restore_keep_identity(monkeypatch,tmp_path):
    import main
    monkeypatch.setenv('VEYORA_CONFIG_DIR',str(tmp_path))
    monkeypatch.setattr(main.DownloadQueueManager,'_process_queue',lambda self:None)
    queue=main.DownloadQueueManager(lambda:None)
    settings=dict(download_dir=str(tmp_path))
    first=queue.add_task('https://example.com/a',settings)
    assert queue.add_task('https://example.com/a',settings)==first
    queue.recovery.flush();queue.shutdown()
    second=main.DownloadQueueManager(lambda:None)
    assert second.tasks=={}  # consent required
    second.restore_previous()
    assert list(second.tasks)==[first]
    second.restore_previous()
    assert list(second.tasks)==[first]
    second.shutdown()
