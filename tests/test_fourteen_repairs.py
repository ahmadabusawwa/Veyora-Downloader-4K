"""Real FFmpeg/yt-dlp checks plus isolated state/logic regressions; no AI mocks claimed as inference."""
import functools,http.server,threading
from pathlib import Path
from types import SimpleNamespace as S
import pytest


@pytest.mark.parametrize('start,end',[('0','0'),('1','0'),('-1','5'),('00:60:00','01:01:00'),('nan','9'),('00:xx','10')])
def test_invalid_clip_intervals(start,end):
    from media_clipping import clip_interval
    with pytest.raises(ValueError):clip_interval(start,end)


def test_clip_interval_limits():
    from media_clipping import clip_interval
    assert clip_interval('00:00:01.25','00:00:03',5)==(1.25,3)
    with pytest.raises(ValueError):clip_interval('1','6',5)


def test_actual_download_clips_and_preserves_full_input(tmp_path):
    from main import DownloadEngine,DEFAULT_SETTINGS
    from translator.video_renderer import run_ffmpeg,get_ffprobe_info
    source=tmp_path/'فيديو أصلي.mp4'
    run_ffmpeg(['-f','lavfi','-i','testsrc2=s=160x90:r=20:d=5','-f','lavfi','-i','sine=frequency=440:duration=5','-c:v','libx264','-threads','2','-c:a','aac',source])
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    from urllib.parse import quote
    folder=tmp_path/'النتائج';results=[]
    task=dict(id='actual-clip',url=f'http://127.0.0.1:{server.server_port}/'+quote(source.name),settings={**DEFAULT_SETTINGS,'clip_enabled':True,'clip_start':'00:00:01','clip_end':'00:00:03','download_subs':False,'save_thumbnail':False,'download_dir':str(folder)})
    original=source.read_bytes()
    try:
        DownloadEngine.download_task(task,lambda *a:None,lambda *a:results.append(a),threading.Event(),threading.Event(),str(folder))
        assert results[0][1],results
        output=Path(task['downloaded_file']);info=get_ffprobe_info(output)
        assert abs(float(info['format']['duration'])-2)<.2
        assert any(s['codec_type']=='audio' for s in info['streams'])
        streams={s['codec_type']:s for s in info['streams']}
        assert abs(float(streams['video'].get('start_time',0))-float(streams['audio'].get('start_time',0)))<.1
        assert source.read_bytes()==original
        assert Path(task['original_downloaded_file']).read_bytes()==original
        assert not list(folder.glob('*.srt'))
    finally:server.shutdown();server.server_close()


def test_clip_subtitles_shift_and_exclude_external_cues(tmp_path):
    from media_clipping import clip_subtitles
    from translator.subtitle_generator import generate_srt,parse_srt
    p=tmp_path/'full.srt';generate_srt([S(start=0,end=1,text='Outside'),S(start=1,end=3,text='Boundary'),S(start=3,end=5,text='Inside'),S(start=5,end=6,text='Outside')],p)
    out=clip_subtitles(p,2,5,tmp_path/'clip.srt');c=parse_srt(out)
    assert [(s.start,s.end,s.text) for s in c]==[(0,1,'Boundary'),(1,3,'Inside')]


@pytest.mark.parametrize('order',[[(2,3),(1,2)],[(0,1),(0,0)]])
def test_nonchronological_or_zero_srt_cannot_replace_existing(order,tmp_path):
    from translator.subtitle_generator import generate_srt
    p=tmp_path/'saved.srt';p.write_text('previous')
    with pytest.raises(ValueError):generate_srt([S(start=a,end=b,text='Speech') for a,b in order],p)
    assert p.read_text()=='previous'


def test_html_entities_are_normalized_without_translating_names(monkeypatch):
    from translator import translation_provider as m
    p=m.DirectTranslatorProvider('en','ar');captured=[]
    tokenizer=S(encode=lambda text,**k:captured.append(text) or ['token'],decode=lambda tokens:'مرحبا &quot;Leon&quot; &amp; Jill')
    monkeypatch.setitem(m._runtimes,p.key,(tokenizer,S(translate_batch=lambda *a,**k:[S(hypotheses=[['piece']])])))
    monkeypatch.setattr(p,'prepare',lambda *a:None)
    assert p.translate('Hello &quot;Leon&quot;')=='مرحبا "Leon" & Jill'
    assert captured==['Hello "Leon"']


def test_automatic_shared_options_preserve_legacy_settings():
    from translator.recognition_policy import configured_translation_options
    old=dict(speech_policy='off',context_policy='off',contextual_translation=False,enhance_speech=False)
    before=dict(old)
    assert configured_translation_options(old)==dict(enhance_speech='auto',contextual_translation=None)
    assert old==before


def test_automatic_candidate_never_drops_recognized_words():
    from translator.automatic_audio import prefer_candidate,needs_candidate
    def cue(text,score,end=4):return S(start=0,end=end,text=text,avg_logprob=score,no_speech_prob=.02,compression_ratio=1.1)
    original=[cue('Hello world today',-.8)]
    assert not prefer_candidate(original,[cue('Hello tomorrow',-.1)])
    assert prefer_candidate(original,[cue('Hello world today',-.3)])
    assert not prefer_candidate(original,[cue('Hello world today',-.7)])
    assert needs_candidate(original,dict(active_seconds=list(range(30)),duration=30))
    assert not needs_candidate([cue('Hello world today',-.1)],dict(active_seconds=[0,1,2],duration=30))


def test_preview_empty_initial_and_invalidates_after_url_edit(monkeypatch,tmp_path):
    import main,json
    from desktop_ui import DesktopApp
    monkeypatch.setattr(main,'SETTINGS_FILE',tmp_path/'settings.json')
    main.SETTINGS_FILE.write_text(json.dumps(dict(auto_update_check=False,ui_language='en',remember_public_links=False,saved_public_url='https://example.com/old')))
    app=DesktopApp()
    try:
        history_before=app.queue_manager.get_tasks_by_status()
        assert app.url_entry.get()==''
        assert 'Beautiful Nature' not in app.preview_title.cget('text')
        app.url_entry.insert(0,'https://example.com/first')
        app.show_preview(dict(title='First real title',duration=5))
        assert app.preview_title.cget('text')=='First real title'
        app.url_entry.delete(0,'end');app.url_entry.insert(0,'https://example.com/second')
        assert app.preview_title.cget('text')!='First real title'
        assert app._analyzed_url is None
        assert app.queue_manager.get_tasks_by_status()==history_before
    finally:app._on_close()


def test_recovered_history_cannot_launch_executable(tmp_path):
    from output_actions import validate_open_target
    file=tmp_path/'unexpected.exe';file.write_bytes(b'not executable')
    with pytest.raises(ValueError,match='Unsafe'):validate_open_target(file)
    assert validate_open_target(file,folder=True)==file.resolve()


def test_actual_split_preserves_full_export_and_timeline(tmp_path):
    from translator.video_renderer import run_ffmpeg,get_ffprobe_info
    from media_clipping import split_long_video
    from translator.subtitle_generator import generate_srt,parse_srt
    media=tmp_path/'full.mp4';captions=tmp_path/'full.srt'
    run_ffmpeg(['-f','lavfi','-i','color=s=160x90:d=3','-c:v','libx264','-threads','2',media])
    generate_srt([S(start=.5,end=2.5,text='مرحبا')],captions)
    before=media.read_bytes();parts=split_long_video(media,tmp_path,seconds=2,subtitle=captions)
    assert len(parts)==2 and media.read_bytes()==before
    assert abs(float(get_ffprobe_info(parts[0])['format']['duration'])-2)<.2
    cue=parse_srt(Path(parts[1]).with_suffix('.srt'))[0]
    assert cue.start==0 and cue.end==.5


def test_unsupported_detected_language_is_never_guessed_as_english(monkeypatch,tmp_path):
    from translator import pipeline
    from translator.exceptions import TranscriptionError
    media=tmp_path/'spanish.mp4';media.write_bytes(b'identity')
    monkeypatch.setattr(pipeline.TranslationPipeline,'_extract_speech',lambda *a:None)
    monkeypatch.setattr(pipeline.TranslationPipeline,'_recognize',lambda *a:([S(start=0,end=2,text='Hola mundo')],S(language='es')))
    with pytest.raises(TranscriptionError,match='not supported'):
        pipeline.TranslationPipeline(media,tmp_path).run(source_lang='auto')
    assert not list(tmp_path.glob('*.srt'))


def test_invalid_user_data_is_preserved_before_saving_defaults(monkeypatch,tmp_path):
    import main
    for name,manager in [('settings',main.SettingsManager),('history',main.HistoryManager)]:
        path=tmp_path/(name+'.json');original=b'not valid JSON \xff';path.write_bytes(original)
        monkeypatch.setattr(main,name.upper()+'_FILE',path)
        values=manager.load()
        if name=='settings':manager.save(values)
        else:manager.add(dict(title='New item'))
        backups=list(tmp_path.glob(name+'.json.invalid-*.bak'))
        assert len(backups)==1 and backups[0].read_bytes()==original
        assert path.read_bytes()!=original


def test_update_dispatch_never_calls_tk_directly_on_worker():
    import threading,queue
    from updater.ui import UpdateUI
    dispatched=[];callback=lambda:dispatched.append(threading.get_ident())
    ui=object.__new__(UpdateUI);ui.app=S(_ui_callbacks=queue.Queue())
    worker=threading.Thread(target=lambda:ui.dispatch(callback));worker.start();worker.join()
    assert not dispatched
    ui.app._ui_callbacks.get_nowait()();assert dispatched==[threading.get_ident()]
    ui.app=S();ui.dispatch(callback);assert len(dispatched)==1


def test_late_metadata_for_changed_link_is_discarded(monkeypatch,tmp_path):
    import main,json,time
    from desktop_ui import DesktopApp
    monkeypatch.setattr(main,'SETTINGS_FILE',tmp_path/'settings.json')
    main.SETTINGS_FILE.write_text(json.dumps(dict(auto_update_check=False,ui_language='en')))
    entered=threading.Event();release=threading.Event()
    def fetch(*args):entered.set();release.wait(3);return dict(title='Stale old title',duration=5)
    monkeypatch.setattr(main.DownloadEngine,'fetch_metadata',fetch)
    app=DesktopApp()
    try:
        app._draft_url.set('https://example.com/old');app.analyze();assert entered.wait(1)
        app._draft_url.set('https://example.com/new');release.set()
        deadline=time.monotonic()+2
        while app._metadata_busy and time.monotonic()<deadline:app.update();threading.Event().wait(.01)
        assert not app._metadata_busy
        assert 'Stale old title' not in app.preview_title.cget('text')
        assert app.url_entry.get()=='https://example.com/new'
    finally:release.set();app._on_close()


@pytest.mark.parametrize('mode',['MOV','AVI'])
def test_actual_additional_video_containers(tmp_path,mode):
    from translator.video_renderer import run_ffmpeg,get_ffprobe_info
    from local_tasks import run_local_job
    source=tmp_path/'source.mp4'
    run_ffmpeg(['-f','lavfi','-i','color=s=160x90:d=1','-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-threads','2','-c:a','aac',source])
    result=run_local_job('Convert',source,tmp_path,'en','ar',mode,checkpoint=lambda:None,progress=lambda *a:None,save_original=False)
    streams=get_ffprobe_info(result['video'])['streams']
    assert {s['codec_type'] for s in streams}=={'video','audio'}
    assert Path(result['video']).suffix=='.'+mode.lower()


def test_audio_navigation_keeps_only_correct_sidebar_item_selected(monkeypatch):
    import main
    from desktop_ui import DesktopApp
    monkeypatch.setitem(main.DEFAULT_SETTINGS,'auto_update_check',False)
    app=DesktopApp()
    try:
        app.home_mode(True)
        app.show_tab('Settings');app.show_tab('Dashboard')
        assert app.mode_var.get()=='Audio (Extract)'
        assert [key for key,button in app._sidebar_buttons.items() if getattr(button,'_veyora_selected',False)]==['audio']
        app.set_mode('Video')
        assert [key for key,button in app._sidebar_buttons.items() if getattr(button,'_veyora_selected',False)]==['video']
    finally:app._on_close()
