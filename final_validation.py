"""Unmocked installed GUI checks for final 2.0.3 fixes."""
import functools
import http.server
import json
import os
from pathlib import Path
import shutil
import threading
import time


def run_final_review(media,folder):
    from desktop_ui import DesktopApp
    from translator.video_renderer import get_ffprobe_info,run_ffmpeg
    from PIL import ImageGrab
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    web=folder/'playlist';web.mkdir(exist_ok=True)
    for name in ('first.mp4','retry.mp4','last.mp4'):shutil.copyfile(media,web/name)
    (web/'index.html').write_text('<title>Authorized retry playlist</title>'+''.join(f'<video src="{name}"></video>' for name in ('first.mp4','retry.mp4','last.mp4')))
    allow_retry=threading.Event()
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            if self.path=='/retry.mp4' and not allow_retry.is_set():self.send_error(404);return
            super().do_GET()
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(web)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    app=DesktopApp();app.settings['ui_language']='en';app.selected_folder=str(folder/'outputs')
    report=dict(ok=False,errors=[],conversion=[])
    state=dict(phase='convert',i=0,waiting=False,deadline=time.monotonic()+180)
    formats=['MP4','MKV','MP3','WAV']
    prefix=f'http://127.0.0.1:{server.server_port}/'
    def finish(error=None):
        if error:report['errors'].append(str(error))
        report['ok']=not report['errors'];(folder/'final-ui-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');app._on_close()
    def tasks():return [t for t in app.queue_manager.get_tasks_by_status() if t.get('url','').startswith(prefix)]
    def poll():
        try:
            assert time.monotonic()<state['deadline'],'Final GUI validation timed out at '+state['phase']
            if state['phase']=='convert':
                app.show_tab('Convert');c=app._local_task_controls
                if not state['waiting']:
                    c['path'].set(str(media));mode=formats[state['i']];c['mode'].set(mode)
                    if mode in ('MP3','WAV'):c['audio_mode'].set(mode);c['extract'].invoke()
                    else:c['start'].invoke()
                    state['waiting']=True
                elif not app.local_tasks.busy:
                    app.show_tab('Convert');t=app.local_tasks.snapshot('Convert');assert t.status=='completed',t.error
                    assert c['play'].cget('state')=='normal' and c['location'].cget('state')=='normal'
                    info=get_ffprobe_info(t.result['video']);assert bool([s for s in info['streams'] if s['codec_type']=='video'])==(formats[state['i']] in ('MP4','MKV'))
                    report['conversion'].append(dict(format=formats[state['i']],file=t.result['video']))
                    state['i']+=1;state['waiting']=False
                    if state['i']==4:state['phase']='playlist_start'
            elif state['phase']=='playlist_start':
                app.show_tab('Playlist');c=app._playlist_controls
                assert c['preferences']['quality'].get()=='best' and not c['preferences']['subtitles'].get()
                c['url'].set(prefix+'index.html');c['load'].invoke();state['phase']='playlist_load'
            elif state['phase']=='playlist_load' and not app._playlist_state['busy']:
                c=app._playlist_controls;assert len(app._playlist_state['entries'])==3
                c['menus']['quality']._dropdown_menu.invoke(3);c['menus']['container']._dropdown_menu.invoke(1)
                c['subtitles'].toggle();assert c['preferences']['subtitles'].get()
                before=len(app.queue_manager.tasks)
                c['download'].invoke()
                for _ in range(20):c['download'].invoke()
                assert len(app.queue_manager.tasks)==before
                app._confirm_controls['no'].invoke();assert len(app.queue_manager.tasks)==before
                c['subtitles'].toggle();assert not c['preferences']['subtitles'].get()
                c['download'].invoke();app._confirm_controls['yes'].invoke();state['phase']='playlist_wait'
            elif state['phase']=='playlist_wait':
                selected=tasks()
                if len(selected)==3 and all(t['status'] in app.queue_manager.TERMINAL for t in selected):
                    failed=[t for t in selected if t['status']=='Failed'];completed=[t for t in selected if t['status']=='Completed']
                    assert len(failed)==1 and len(completed)==2
                    assert failed[0]['error'] and failed[0]['progress']<1
                    for t in completed:
                        assert Path(t['downloaded_file']).suffix=='.mkv'
                        assert t['settings']['quality']=='720p (HD)' and not t['settings']['download_subs']
                    state['completed_mtime']={t['id']:Path(t['downloaded_file']).stat().st_mtime_ns for t in completed}
                    allow_retry.set();app.show_tab('Downloads')
                    app._card_buttons[failed[0]['id']]['retry'].invoke();state['phase']='retry'
            elif state['phase']=='retry' and all(t['status']=='Completed' for t in tasks()):
                assert len(tasks())==3
                for t in tasks():
                    if t['id'] in state['completed_mtime']:assert Path(t['downloaded_file']).stat().st_mtime_ns==state['completed_mtime'][t['id']]
                report['playlist_defaults_review_failure_retry_no_redownload']=True
                app.settings['ui_language']='ar';app.toggle_language();app.toggle_language();app.show_tab('Translation')
                c=app._local_task_controls
                subtitle=folder/'حالة مرجعية.srt';subtitle.write_text('1\n00:00:00,000 --> 00:00:01,000\nمرحبا بالعالم\n',encoding='utf8')
                c['path'].set(str(subtitle));c['source'].set(app._label_for_lang('ar'));c['target'].set(app._label_for_lang('ar',False));c['start'].invoke()
                state['phase']='local_result'
            elif state['phase']=='local_result' and not app.local_tasks.busy:
                app._refresh_local_tasks(True);t=app.local_tasks.snapshot('Translation');assert t.status=='completed',t.error
                app.show_tab('Downloads');app.render_download_items()
                assert app.queue_manager.tasks[t.id]['subtitle_file']==t.result['subtitle']
                assert app._card_buttons[t.id]['subtitle'].winfo_manager()
                report['local_subtitle_result_in_downloads']=True
                app.show_tab('Translation')
                from media_options_ui import subtitle_options
                c=app._local_task_controls;c['path'].set(str(media));subtitle_options(app,c['path']);state['phase']='preview_first';state['subtitle_task_id']=t.id
            elif state['phase']=='preview_first' and app._subtitle_options_window._preview_revision:
                w=app._subtitle_options_window;state['image']=w._preview_image.cget('light_image').tobytes();state['revision']=w._preview_revision
                w._style_controls['size_percent'].set('6');w._style_controls['color'].set('#FFEE00');w._style_controls['position'].set('top');state['phase']='preview_changed'
            elif state['phase']=='preview_changed' and app._subtitle_options_window._preview_revision>state['revision']:
                w=app._subtitle_options_window;assert w._preview_image.cget('light_image').tobytes()!=state['image'];report['live_preview_updates_without_refresh']=True
                ImageGrab.grab().save(folder/'arabic-live-preview.png');w.destroy()
                # Real conversion active while the localized close dialog is rejected.
                app.show_tab('Convert');c=app._local_task_controls;c['path'].set(str(media));c['mode'].set('MP4');c['start'].invoke()
                app.request_close();assert app._confirm_controls is not None
                assert app._confirm_controls['yes'].cget('text') not in ('Yes','No')
                state['phase']='visible_close_dialog'
            elif state['phase']=='visible_close_dialog' and app._confirm_controls['window'].winfo_viewable():
                ImageGrab.grab().save(folder/'arabic-close-dialog.png');app._confirm_controls['no'].invoke()
                app.local_tasks.cancel('Convert');state['phase']='closing_cancel'
            elif state['phase']=='closing_cancel' and not app.local_tasks.busy:
                report['arabic_close_no_preserves_app_and_cancellation']=True
                if os.name=='nt':
                    app.show_tab('Downloads');app.render_download_items()
                    app._card_buttons[state['subtitle_task_id']]['subtitle'].invoke()
                    app._card_buttons[state['subtitle_task_id']]['show'].invoke()
                    state['phase']='opened_files'
                else:
                    report['native_file_open']='Not run outside Windows';finish();return
            elif state['phase']=='opened_files':
                opened=getattr(app,'_opened_outputs',[])
                if len(opened)>=2:
                    report['native_file_open_requests']=opened
                    finish();return
            app.after(50,poll)
        except Exception:
            import traceback
            finish(traceback.format_exc())
    app.after(150,poll);app.mainloop();server.shutdown();server.server_close();thread.join(2)
    return 0 if report['ok'] else 1


def run_close_review(media,folder,kind):
    from desktop_ui import DesktopApp
    from main import DEFAULT_SETTINGS
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    app=DesktopApp();app.settings.update(ui_language='ar',auto_update_check=False)
    report=dict(ok=False,kind=kind,errors=[]);state=dict(deadline=time.monotonic()+50,phase='start',yes=False)
    server=None
    if kind=='download':
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self,*a):pass
            def copyfile(self,source,output):
                try:
                    while chunk:=source.read(8192):
                        output.write(chunk);output.flush();time.sleep(.04)
                except (BrokenPipeError,ConnectionResetError):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(Path(media).parent)))
        threading.Thread(target=server.serve_forever,daemon=True).start()
    def poll():
        try:
            assert time.monotonic()<state['deadline'],'Close review timeout'
            if state['phase']=='start':
                if kind=='download':
                    settings={**DEFAULT_SETTINGS,'download_subs':False,'save_thumbnail':False,'download_dir':str(folder/'downloads'),'speed_limit':32}
                    from urllib.parse import quote
                    app.queue_manager.add_task(f'http://127.0.0.1:{server.server_port}/'+quote(Path(media).name),settings)
                elif kind=='translation':
                    app.show_tab('Translation');c=app._local_task_controls;c['path'].set(str(media));c['source'].set(app._label_for_lang('en'));c['target'].set(app._label_for_lang('ar',False));c['start'].invoke()
                else:
                    state['yes']=True;app.request_close();return
                state['phase']='active'
            elif state['phase']=='active':
                if kind=='download':
                    current=app.queue_manager.get_tasks_by_status()
                    report['last_download_tasks']=[{key:t.get(key) for key in ('id','status','progress','speed','filesize','error','downloaded_file')} for t in current]
                    active=any(t['status']=='Downloading' and t['progress']>0 for t in current)
                    if current and all(t['status'] in app.queue_manager.TERMINAL for t in current):
                        raise RuntimeError('Download ended before active-close test: '+str(report['last_download_tasks']))
                else:
                    task=app.local_tasks.snapshot('Translation');active=task and task.stage.startswith('Recognizing')
                if active:
                    app.request_close();state['phase']='confirm_no'
            elif state['phase']=='confirm_no' and app._confirm_controls['window'].winfo_viewable():
                from PIL import ImageGrab
                ImageGrab.grab().save(folder/'close-no.png')
                app._confirm_controls['no'].invoke()
                assert not app.local_tasks.closed
                report['no_kept_app_open']=True
                state['phase']='reopen'
            elif state['phase']=='reopen':
                app.request_close();state['phase']='confirm_yes'
            elif state['phase']=='confirm_yes' and app._confirm_controls['window'].winfo_viewable():
                from PIL import ImageGrab
                ImageGrab.grab().save(folder/'close-yes.png')
                state['yes']=True;state['yes_time']=time.monotonic();app._confirm_controls['yes'].invoke();return
            app.after(50,poll)
        except Exception:
            import traceback
            report['errors'].append(traceback.format_exc());app._on_close()
    app.after(100,poll);app.mainloop()
    if server:server.shutdown();server.server_close()
    if kind=='download':
        try:
            app.queue_manager.recovery.thread.join(2)
            saved=app.queue_manager.recovery.load();assert any(t['status'] not in app.queue_manager.TERMINAL for t in saved)
            parts=list((folder/'downloads').glob('*.part'))
            assert parts and any(0<part.stat().st_size<Path(media).stat().st_size for part in parts),'No incomplete real media part at close'
            report['partial_files']=[dict(name=part.name,bytes=part.stat().st_size) for part in parts]
            report['unfinished_download_durable']=True
        except Exception as exc:report['errors'].append(str(exc))
    report['yes_closed_app']=state['yes'] and getattr(app,'_closing',False)
    report['seconds_after_yes']=time.monotonic()-state.get('yes_time',time.monotonic())
    report['ok']=not report['errors'] and report['yes_closed_app']
    (folder/'close-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    return 0 if report['ok'] else 1
