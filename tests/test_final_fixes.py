import subprocess
import time
from pathlib import Path
import pytest


def test_conversion_buttons_real_outputs(monkeypatch,tmp_path):
    import main
    from desktop_ui import DesktopApp
    from translator.video_renderer import executable,get_ffprobe_info
    monkeypatch.setitem(main.DEFAULT_SETTINGS,'auto_update_check',False)
    source=tmp_path/'فيديو بصوت.mp4'
    subprocess.run([executable('ffmpeg'),'-v','error','-f','lavfi','-i','color=s=320x180:d=2','-f','lavfi','-i','sine=frequency=440:duration=2','-c:v','libx264','-threads','2','-c:a','aac',str(source)],check=True)
    app=DesktopApp();app.selected_folder=str(tmp_path/'outputs');app.show_tab('Convert')
    controls=app._local_task_controls;controls['path'].set(str(source))
    expected=['MP4','MKV','MP3','WAV'];outputs=[];errors=[];state={'index':0,'waiting':False};deadline=time.monotonic()+45
    def poll():
        try:
            assert time.monotonic()<deadline
            if not state['waiting']:
                mode=expected[state['index']]
                controls['mode'].set(mode)
                if mode in ('MP3','WAV'):
                    controls['audio_mode'].set(mode);controls['extract'].invoke()
                else:controls['start'].invoke()
                state['waiting']=True
            elif not app.local_tasks.busy:
                app.show_tab('Convert')
                task=app.local_tasks.snapshot('Convert');assert task.status=='completed',task.error
                path=Path(task.result['video']);assert path.is_file()
                streams=get_ffprobe_info(path)['streams']
                assert any(s['codec_type']=='video' for s in streams)==(expected[state['index']] in ('MP4','MKV'))
                assert controls['play'].cget('state')=='normal'
                assert controls['location'].cget('state')=='normal'
                assert app.local_tasks.snapshot('Translation') is None
                outputs.append(path);state['index']+=1;state['waiting']=False
                if state['index']==len(expected):app.quit();return
            app.after(30,poll)
        except Exception as exc:errors.append(exc);app.quit()
    try:
        app.after(20,poll);app.mainloop();assert not errors,errors
        assert len(outputs)==4
    finally:app._on_close()


def test_audio_failure_is_visible_and_not_success(monkeypatch,tmp_path):
    import main
    from desktop_ui import DesktopApp
    monkeypatch.setitem(main.DEFAULT_SETTINGS,'auto_update_check',False)
    app=DesktopApp();app.show_tab('Convert');controls=app._local_task_controls
    controls['path'].set(str(tmp_path/'missing.mp4'));controls['mode'].set('WAV');controls['start'].invoke()
    deadline=time.monotonic()+3
    while app.local_tasks.busy and time.monotonic()<deadline:time.sleep(.01)
    try:
        app.show_tab('Convert')
        assert app.local_tasks.snapshot('Convert').status=='failed'
        assert controls['play'].cget('state')=='disabled'
        assert controls['status'].cget('text')
    finally:app._on_close()


def test_playlist_does_not_inherit_dashboard_translation_or_4k():
    from playlist_options import playlist_settings
    from main import DownloadEngine
    settings=playlist_settings(dict(download_subs=True,sub_lang='auto-ar',quality='2160p (4K)',extract_audio=True))
    assert settings['quality']=='Best Available' and not settings['download_subs'] and not settings['extract_audio']
    assert DownloadEngine.get_format_string(settings)=='bestvideo+bestaudio/best'
    settings=playlist_settings({},quality='720',subtitles=True,source='en',target='ar')
    assert settings['sub_lang']=='auto-ar' and '720' in DownloadEngine.get_format_string(settings)
    assert '/best' not in DownloadEngine.get_format_string(settings).split('bestaudio')[-1].replace('/best[','')


def test_completed_output_and_subtitle_survive_restart(monkeypatch,tmp_path):
    import main
    monkeypatch.setenv('VEYORA_CONFIG_DIR',str(tmp_path))
    q=main.DownloadQueueManager(lambda:None)
    saved=dict(id='final',url='https://example.com/x',status='Completed',downloaded_file=str(tmp_path/'translated.mp4'),subtitle_file=str(tmp_path/'captions.srt'))
    q.recovery.submit([saved]);q.recovery.flush();q.shutdown()
    # shutdown saves manager's actual list; seed a closed producer's durable result for this fixture.
    q.recovery.thread.join(2)
    from recovery_store import RecoveryStore
    store=RecoveryStore(q.recovery.path);store.submit([saved]);store.flush();store.close();store.thread.join(2)
    restored=main.DownloadQueueManager(lambda:None)
    try:
        from output_actions import final_output
        assert restored.tasks['final']['status']=='Completed'
        assert final_output(restored.tasks['final'],'subtitle')==saved['subtitle_file']
        assert restored.futures=={} and restored.recoverable==[]
    finally:restored.shutdown()


def test_live_preview_updates_without_pressing_refresh(monkeypatch,tmp_path):
    import main
    import customtkinter as ctk
    from desktop_ui import DesktopApp
    from media_options_ui import subtitle_options
    monkeypatch.setitem(main.DEFAULT_SETTINGS,'auto_update_check',False)
    for kind in (DesktopApp,ctk.CTkToplevel):
        monkeypatch.setattr(kind,'winfo_screenwidth',lambda self:1024)
        monkeypatch.setattr(kind,'winfo_screenheight',lambda self:768)
    app=DesktopApp();app.show_tab('Translation')
    subtitle_options(app,app._local_task_controls['path']);window=app._subtitle_options_window
    state={'phase':0,'first':None};errors=[];deadline=time.monotonic()+12
    def poll():
        try:
            assert time.monotonic()<deadline
            if state['phase']==0 and window._preview_revision:
                dimensions=window.geometry().split('+')
                width,height=map(int,dimensions[0].split('x'))
                assert width+int(dimensions[1])<=1024 and height+int(dimensions[2])+40<=728
                state['first']=window._preview_image.cget('light_image').tobytes()
                state['revision']=window._preview_revision
                window._style_controls['color'].set('#FFFF00');window._style_controls['size_percent'].set('6')
                window._style_controls['position'].set('top')
                assert window._position_menu.get()==app.t('أعلى الفيديو','Top')
                assert window._style_sliders[0].get()==6
                state['phase']=1
            elif state['phase']==1 and window._preview_revision>state['revision']:
                assert window._preview_image.cget('light_image').tobytes()!=state['first']
                app.quit();return
            app.after(30,poll)
        except Exception as exc:errors.append(exc);app.quit()
    try:
        app.after(30,poll);app.mainloop();assert not errors,errors
    finally:window.destroy();app._on_close()


def test_native_arabic_menu_keeps_logical_labels_and_codes():
    from ui_controls import native_label
    from main import fix_arabic_text
    from desktop_ui import DesktopApp
    for code,name in [('ar','العربية'),('en','الإنجليزية'),('tr','التركية'),('ko','الكورية')]:
        shown=fix_arabic_text(f'({code}) {name}')
        raw=native_label(shown)
        assert name in raw and code in raw
        assert not any('\ufb50'<=c<='\ufeff' for c in raw)
        assert DesktopApp._lang_code(shown)==code


def test_auto_speech_does_not_force_unproven_processing():
    from translator.recognition_policy import should_enhance,automatic_context
    from types import SimpleNamespace as S
    assert not should_enhance('auto') and not should_enhance('off') and should_enhance('on')
    unchanged=list(automatic_context([S(start=0,end=1,text='Hello world.'),S(start=1,end=2,text='Today is sunny.')]))
    assert len(unchanged)==2
    merged=list(automatic_context([S(start=0,end=2,text='I bought flowers.'),S(start=2,end=4,text='They bloom in spring.')]))
    assert len(merged)==1


def test_close_confirmation_no_keeps_running_task(monkeypatch,tmp_path):
    import main,threading
    from desktop_ui import DesktopApp
    monkeypatch.setitem(main.DEFAULT_SETTINGS,'auto_update_check',False)
    app=DesktopApp()
    def wait(*args,checkpoint,**kwargs):
        while True:checkpoint();threading.Event().wait(.01)
    app.local_tasks.start('Translation','x.mp4',tmp_path,'en','ar','separate',runner=wait)
    try:
        app.request_close()
        controls=app._confirm_controls
        assert controls['yes'].cget('text') not in ('Yes','No')
        controls['no'].invoke()
        assert app.local_tasks.busy and not app.local_tasks.closed
    finally:app._on_close()


def test_confirmation_reuses_window_and_resolves_once(monkeypatch):
    import main
    from desktop_ui import DesktopApp
    from confirmation import confirm
    monkeypatch.setitem(main.DEFAULT_SETTINGS,'auto_update_check',False)
    app=DesktopApp();accepted=[]
    try:
        first=None;binding=None
        for index in range(20):
            app.settings['ui_language']='en' if index%2==0 else 'ar'
            controls=confirm(app,'تأكيد','Confirm','تجربة','Test',lambda i=index:accepted.append(i))
            assert controls['yes'].cget('text')==app.t('نعم','Yes')
            assert controls['no'].cget('text')==app.t('لا','No')
            if first is None:
                first=controls['window'];binding=app.bind_all('<Button-1>')
            assert controls['window'] is first
            assert app.bind_all('<Button-1>')==binding
            controls['yes'].invoke();controls['yes'].invoke()
            assert app._confirm_controls is None
            assert first.winfo_exists()
            app.update()
        assert accepted==list(range(20))
    finally:app._on_close()


def test_network_progress_restores_download_state_after_preprocessing(monkeypatch,tmp_path):
    import main,threading
    entered=threading.Event();release=threading.Event()
    def download(task,progress,complete,*args):
        progress(task['id'],dict(status='finished'))
        progress(task['id'],dict(status='downloading',downloaded_bytes=100,total_bytes=1000))
        entered.set();release.wait(3)
        complete(task['id'],False,'Test stopped')
    monkeypatch.setattr(main.DownloadEngine,'download_task',download)
    monkeypatch.setattr(main,'CONFIG_DIR',tmp_path)
    monkeypatch.setenv('VEYORA_CONFIG_DIR',str(tmp_path))
    manager=main.DownloadQueueManager(lambda:None)
    try:
        tid=manager.add_task('https://example.com/video.mp4',main.DEFAULT_SETTINGS)
        assert entered.wait(3)
        task=manager.get_tasks_by_status()[0]
        assert task['id']==tid and task['status']=='Downloading' and task['progress']==.1
    finally:release.set();manager.shutdown()
