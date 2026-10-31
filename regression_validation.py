"""Unmocked packaged Windows checks; actual customer-video diagnosis is separate."""
import hashlib,json,os,threading,time
from pathlib import Path


def run_regression_review(media,folder):
    if os.name!='nt' or os.environ.get('VEYORA_REVIEW_NETWORK_BLOCKED')!='1':
        raise RuntimeError('Run native recognition only in the verified Windows firewall fixture')
    from desktop_ui import DesktopApp
    from translator.video_renderer import run_ffmpeg,get_ffprobe_info
    from translator.subtitle_generator import parse_srt
    from ui_controls import native_label
    from PIL import ImageGrab
    import ctypes
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    fixture=folder/'continuous-speech.mp4'
    run_ffmpeg(['-i',media,'-t','20','-c','copy',fixture])
    duration=float(get_ffprobe_info(fixture)['format']['duration'])
    before=hashlib.sha256(fixture.read_bytes()).hexdigest()
    app=DesktopApp();app.settings.update(ui_language='ar',save_original_subtitles=True)
    app.selected_folder=str(folder/'outputs');app.show_tab('Translation')
    c=app._local_task_controls
    app.show_tab('Dashboard')
    report=dict(ok=False,errors=[],scope='Real SAPI speech, actual installed app and Whisper/Argos/FFmpeg; customer clip is unavailable',cases=[])
    state=dict(phase='recovery',index=0,deadline=time.monotonic()+180)
    import functools,http.server
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(folder)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    menu_done=threading.Event()
    missing_done=threading.Event();missing_seen=[]
    def finish(error=None):
        if state.get('missing_path') and not state['missing_path'].exists():state['missing_path'].write_bytes(state['missing_bytes'])
        server.shutdown();server.server_close()
        if error:report['errors'].append(str(error))
        report['ok']=not report['errors']
        (folder/'regression-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        app._on_close()
    def capture_menu(window_id):
        # Screenshots and native input only. No Tk objects enter this thread.
        try:
            time.sleep(.4)
            ImageGrab.grab().save(folder/'expanded-language.png')
        finally:
            from ctypes import wintypes
            api=ctypes.WinDLL('user32',use_last_error=True)
            api.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];api.GetAncestor.restype=wintypes.HWND
            api.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM];api.PostMessageW.restype=wintypes.BOOL
            owner=api.GetAncestor(window_id,2) or window_id
            # Cancel the menu owned by this application, not whichever external
            # window happens to have keyboard focus on the CI desktop.
            api.PostMessageW(owner,0x1F,0,0) # WM_CANCELMODE
            api.PostMessageW(owner,0x100,0x1B,0)
            menu_done.set()
    def acknowledge_missing_file():
        # Drive the real native error dialog on the disposable Windows desktop.
        # Explicit 64-bit Win32 signatures; this worker never owns Tk objects.
        from ctypes import wintypes
        api=ctypes.WinDLL('user32',use_last_error=True)
        api.FindWindowW.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR];api.FindWindowW.restype=wintypes.HWND
        api.GetDlgItem.argtypes=[wintypes.HWND,ctypes.c_int];api.GetDlgItem.restype=wintypes.HWND
        api.SendMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM];api.SendMessageW.restype=ctypes.c_ssize_t
        limit=time.monotonic()+8
        try:
            while time.monotonic()<limit:
                window=api.FindWindowW('#32770','فيفورا برو')
                if window:
                    ImageGrab.grab().save(folder/'missing-output-error.png')
                    missing_seen.append(True)
                    api.SendMessageW(api.GetDlgItem(window,1),0xF5,0,0)
                    return
                time.sleep(.05)
        finally:missing_done.set()
    def inspect_recovery_dialog():
        from ctypes import wintypes
        api=ctypes.WinDLL('user32',use_last_error=True)
        api.FindWindowW.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR];api.FindWindowW.restype=wintypes.HWND
        api.GetDlgItem.argtypes=[wintypes.HWND,ctypes.c_int];api.GetDlgItem.restype=wintypes.HWND
        api.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int];api.GetWindowTextW.restype=ctypes.c_int
        api.SendMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM];api.SendMessageW.restype=ctypes.c_ssize_t
        limit=time.monotonic()+8
        while time.monotonic()<limit:
            window=api.FindWindowW('#32770','استعادة التحميلات')
            if window:
                texts=[]
                callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
                def read_child(child,unused):
                    text=ctypes.create_unicode_buffer(4096);api.GetWindowTextW(child,text,4096)
                    if text.value:texts.append(text.value)
                    return True
                callback=callback_type(read_child)
                api.EnumChildWindows.argtypes=[wintypes.HWND,callback_type,wintypes.LPARAM];api.EnumChildWindows.restype=wintypes.BOOL
                api.EnumChildWindows(window,callback,0)
                report['recovery_dialog_text']='\n'.join(texts)
                ImageGrab.grab().save(folder/'recovery-confirmation.png')
                api.SendMessageW(api.GetDlgItem(window,7),0xF5,0,0)
                return
            time.sleep(.05)
        report['recovery_dialog_text']='NOT FOUND'

    def poll():
        try:
            (folder/'regression-state.json').write_text(json.dumps(dict(phase=state['phase'],elapsed=180-(state['deadline']-time.monotonic())),indent=2),encoding='utf8')
            assert time.monotonic()<state['deadline'],'Native regression review timed out at '+state['phase']
            if state['phase']=='recovery':
                threading.Thread(target=inspect_recovery_dialog,daemon=True,name='native-recovery-dialog-review').start()
                app._offer_download_recovery()
                text=report.get('recovery_dialog_text','')
                assert 'توجد تحميلات' in text and not any('\ufb50'<=x<='\ufeff' for x in text),text
                report['native_recovery_dialog_logical_arabic']='PASS'
                app.home_mode(True);app.show_tab('Settings');app.show_tab('Dashboard')
                assert [key for key,button in app._sidebar_buttons.items() if getattr(button,'_veyora_selected',False)]==['audio']
                app.home_mode(False)
                assert [key for key,button in app._sidebar_buttons.items() if getattr(button,'_veyora_selected',False)]==['video']
                report['audio_video_sidebar_selection']='PASS'
                state['phase']='language'
            elif state['phase']=='language':
                menu=app.source_menu;value=app._label_for_lang('auto');menu.set(value)
                assert app._lang_code(app.source_var.get())=='auto'
                assert menu._text_label.cget('text')==native_label(value)
                assert not any('\ufb50'<=letter<='\ufeff' for letter in menu._text_label.cget('text'))
                state['phase']='language_painted'
            elif state['phase']=='language_painted':
                ImageGrab.grab().save(folder/'selected-language.png')
                menu=app.source_menu
                for index,value in enumerate(menu._values):assert menu._dropdown_menu.entrycget(index,'label')==native_label(value)
                threading.Thread(target=capture_menu,args=(app.winfo_id(),),daemon=True,name='native-menu-capture').start()
                state['phase']='menu_wait'
                menu._dropdown_menu.post(menu.winfo_rootx(),menu.winfo_rooty()+menu.winfo_height())
            elif state['phase']=='menu_wait' and menu_done.is_set():
                report['arabic_selected_and_expanded_labels']='PASS'
                app.show_tab('Translation')
                c['source'].set(app._label_for_lang('en'));c['target'].set(app._label_for_lang('ar',False));c['path'].set(str(fixture))
                state['phase']='start'
            elif state['phase']=='start':
                app.settings.update(speech_policy='off' if state['index']==0 else 'on',context_policy='off' if state['index']==0 else 'on')
                assert 'enhance_speech' not in c and 'contextual_translation' not in c
                c['start'].invoke()
                assert c['open_subtitle'].cget('state')=='disabled'
                state['phase']='running'
            elif state['phase']=='running' and not app.local_tasks.busy:
                app._refresh_local_tasks(True);task=app.local_tasks.snapshot('Translation')
                assert task.status=='completed',task.error
                result=task.result;captions=parse_srt(result['subtitle']);source=parse_srt(result['source_subtitle'])
                # This generated fixture contains repeating known speech at its end.
                assert max(s.end for s in source)>=duration-3,'Recognized fixture tail is missing'
                assert max(s.end for s in captions)>=duration-3,'Translated fixture tail is missing'
                assert c['open_subtitle'].cget('state')=='normal' and c['open_folder'].cget('state')=='normal'
                assert c['open_video'].cget('text')==app.t('فتح الملف الأصلي','Open original media')
                report['cases'].append(dict(enhance='auto',context='auto',
                    original_transcript=Path(result['source_subtitle']).read_text(encoding='utf8'),
                    arabic_subtitles=Path(result['subtitle']).read_text(encoding='utf8'),duration=duration,
                    last_recognition_end=max(s.end for s in source),last_srt_end=max(s.end for s in captions)))
                if state['index']==0:state['index']=1;state['phase']='start'
                else:
                    from main import DEFAULT_SETTINGS
                    settings={**DEFAULT_SETTINGS,**app.settings,'download_dir':str(folder/'downloaded'),'download_subs':True,'sub_lang':'auto-ar','subtitle_mode':'burn','format':'MP4','save_thumbnail':False,'clip_enabled':False,'save_original_subtitles':True}
                    state['download_settings']=settings
                    state['download_id']=app.queue_manager.add_task(f'http://127.0.0.1:{server.server_port}/continuous-speech.mp4',settings,selected_folder=str(folder/'downloaded'))
                    state['phase']='download_wait'
            elif state['phase']=='download_wait':
                task=next(t for t in app.queue_manager.get_tasks_by_status() if t['id']==state['download_id'])
                if task['status'] in ('Failed','Cancelled'):raise AssertionError(task.get('error'))
                if task['status']=='Completed':
                    downloaded=parse_srt(task['subtitle_file'])
                    local=parse_srt(app.local_tasks.snapshot('Translation').result['subtitle'])
                    assert [(s.start,s.end,s.text) for s in downloaded]==[(s.start,s.end,s.text) for s in local]
                    assert Path(task['downloaded_file']).suffix=='.mp4'
                    assert any(s['codec_type']=='video' for s in get_ffprobe_info(task['downloaded_file'])['streams'])
                    report['shared_local_download_engine']='PASS: actual HTTP/yt-dlp + native translation, matching Arabic cues, rendered MP4'
                    state['download_settings']['clip_enabled']=True;state['download_settings']['clip_start']='00:00:02';state['download_settings']['clip_end']='00:00:18'
                    state['clip_id']=app.queue_manager.add_task(f'http://127.0.0.1:{server.server_port}/continuous-speech.mp4?clip=1',state['download_settings'],selected_folder=str(folder/'clipped'))
                    state['phase']='clip_wait'
            elif state['phase']=='clip_wait':
                task=next(t for t in app.queue_manager.get_tasks_by_status() if t['id']==state['clip_id'])
                if task['status'] in ('Failed','Cancelled'):raise AssertionError(task.get('error'))
                if task['status']=='Completed':
                    length=float(get_ffprobe_info(task['downloaded_file'])['format']['duration'])
                    assert abs(length-16)<.3
                    cues=parse_srt(task['subtitle_file']);assert all(0<=s.start<s.end<=length+.05 for s in cues)
                    report['actual_download_clip_translation']='PASS: nonzero 2..18 interval, real 16s MP4, clip-relative SRT'
                    ImageGrab.grab().save(folder/'completed-results.png')
                    state['opened_before']=len(getattr(app,'_opened_outputs',[]))
                    c['open_subtitle'].invoke();c['open_folder'].invoke()
                    if os.environ.get('VEYORA_REVIEW_VIDEO_ASSOCIATION')=='1':c['open_video'].invoke()
                    else:report['open_video']='NOT TESTED: no verified disposable video association'
                    state['phase']='opened'
            elif state['phase']=='opened':
                expected=3 if os.environ.get('VEYORA_REVIEW_VIDEO_ASSOCIATION')=='1' else 2
                opened=getattr(app,'_opened_outputs',[])[state['opened_before']:]
                if len(opened)>=expected:
                    report['native_open_requests']=opened
                    if expected==3:report['open_video']='PASS: original media opened through disposable test association'
                    audit=Path(os.environ['VEYORA_REVIEW_AUDIT_DIR'])/'pipeline-events.jsonl'
                    events=[json.loads(line) for line in audit.read_text(encoding='utf8').splitlines()]
                    extracted=[event for event in events if event['event']=='audio_extraction']
                    contexts=[event for event in events if event['event']=='translation_context']
                    assert extracted and all(event['enhanced'] is False for event in extracted)
                    assert len(contexts)>=3 and all(event['policy'] is None for event in contexts)
                    assert any(event['event']=='automatic_dialogue' for event in events)
                    assert hashlib.sha256(fixture.read_bytes()).hexdigest()==before
                    report.update(pipeline_events=events,original_video_unchanged=True,automatic_shared_engine_reached_native_backend='PASS')
                    missing=Path(app.local_tasks.snapshot('Translation').result['subtitle'])
                    state['missing_path']=missing;state['missing_bytes']=missing.read_bytes();missing.unlink()
                    threading.Thread(target=acknowledge_missing_file,daemon=True,name='native-error-review').start()
                    c['open_subtitle'].invoke();state['phase']='missing_file'
            elif state['phase']=='missing_file' and missing_done.is_set():
                state['missing_path'].write_bytes(state['missing_bytes'])
                assert missing_seen,'Missing file did not display the native error dialog'
                assert app.local_tasks.snapshot('Translation').status=='completed'
                report['deleted_output_error_handled']='PASS: real missing file, native error acknowledged, fixture restored'
                report['multilingual']=[];state['matrix_index']=0;state['phase']='matrix_start'
            elif state['phase']=='matrix_start':
                samples=[('en','Hello world. Today the weather is beautiful.'),('ar','مرحبا بالعالم. الطقس جميل اليوم.'),('tr','Merhaba dünya. Bugün hava güzel.'),('ko','안녕하세요. 오늘 날씨가 좋습니다.')]
                language,text=samples[state['matrix_index']]
                from translator.subtitle_generator import generate_srt
                from types import SimpleNamespace
                source_file=folder/(language+'-reference.srt');generate_srt([SimpleNamespace(start=0,end=5,text=text)],source_file)
                app.show_tab('Translation');c['path'].set(str(source_file));c['source'].set(app._label_for_lang(language));c['target'].set(app._label_for_lang('ar',False));c['start'].invoke()
                state['matrix_language']=language;state['phase']='matrix_wait'
            elif state['phase']=='matrix_wait' and not app.local_tasks.busy:
                app._refresh_local_tasks(True);task=app.local_tasks.snapshot('Translation')
                assert task.status=='completed',task.error
                cues=parse_srt(task.result['subtitle']);assert cues and cues[0].start==0 and cues[0].end==5
                report['multilingual'].append(dict(language=state['matrix_language'],srt_text_translation='PASS',speech_recognition='NOT TESTED by this SRT test',output=cues[0].text,quality='Reviewable output; not a human accuracy certification'))
                state['matrix_index']+=1
                if state['matrix_index']==4:finish();return
                state['phase']='matrix_start'
            app.after(75,poll)
        except Exception:
            import traceback
            finish(traceback.format_exc())
    import faulthandler
    with (folder/'hang-traces.log').open('w',encoding='utf8') as trace:
        faulthandler.dump_traceback_later(90,repeat=True,file=trace)
        try:app.after(300,poll);app.mainloop()
        finally:faulthandler.cancel_dump_traceback_later()
    return 0 if report['ok'] else 1
