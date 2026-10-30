"""Real installed-media checks. Reports measurements without inventing quality gains."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def _write(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf8')


def wer(reference,hypothesis):
    a=re.findall(r'\w+',reference.lower());b=re.findall(r'\w+',hypothesis.lower())
    row=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        current=[i]
        for j,y in enumerate(b,1):
            current.append(min(current[-1]+1,row[j]+1,row[j-1]+(x!=y)))
        row=current
    return row[-1]/max(1,len(a))


def quality_review(wave,folder):
    if os.environ.get('VEYORA_REVIEW_NETWORK_BLOCKED') != '1':
        raise RuntimeError('Native quality tests require verified firewall isolation')
    from translator.transcription import Transcriber,release_speech_model
    from translator.translation_provider import TranslatorProvider,release_translation_models
    from translator.video_renderer import extract_audio,run_ffmpeg,preview_subtitles,get_ffprobe_info,burn_subtitles
    from translator.speech_enhancement import enhance_speech
    from translator.context_segments import sentence_groups
    from types import SimpleNamespace
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    report=dict(ok=False,errors=[],recognition=[],translation=[],limitations=['Synthetic SAPI speech and synthesized accompaniment; human singing accuracy has not been verified.','Center enhancement is not neural separation and cannot recover all speech under music.'])
    reference='Hello world. Today the weather is beautiful. Please download this video and save the subtitles.'
    try:
        recognizer=Transcriber(language='en')
        for name in ('ordinary','loud_music','pitch_modulated_vocal'):
            media=folder/(name+'.wav')
            if name=='ordinary':
                import shutil
                shutil.copyfile(wave,media)
            else:
                # Known reference speech; deterministic original accompaniment, not downloaded copyrighted music.
                speech_filter='[0:a]aformat=channel_layouts=stereo,volume=0.5[s];'
                if name=='pitch_modulated_vocal':
                    speech_filter='[0:a]vibrato=f=5:d=0.6,aformat=channel_layouts=stereo,volume=0.5[s];'
                run_ffmpeg(['-i',wave,'-f','lavfi','-i','aevalsrc=0.35*sin(2*PI*220*t)+0.2*sin(2*PI*330*t)|0.35*sin(2*PI*277*t)+0.2*sin(2*PI*415*t):s=16000:d=30',
                    '-filter_complex',speech_filter+'[s][1:a]amix=inputs=2:duration=first:normalize=0[out]', '-map','[out]',media])
            for enhanced in (False,True):
                audio=folder/(name+('-enhanced' if enhanced else '-baseline')+'.wav')
                started=time.monotonic()
                (enhance_speech if enhanced else extract_audio)(media,audio)
                segments,_=recognizer.transcribe(str(audio))
                text=' '.join(s.text.strip() for s in segments)
                report['recognition'].append(dict(sample=name,enhanced=enhanced,reference=reference,text=text,wer=wer(reference,text),seconds=round(time.monotonic()-started,3)))
        pairs={name:[r for r in report['recognition'] if r['sample']==name] for name in ('ordinary','loud_music','pitch_modulated_vocal')}
        report['speech_improvement_verified_on_fixture'] = pairs['loud_music'][1]['wer'] < pairs['loud_music'][0]['wer'] and pairs['ordinary'][1]['wer'] <= pairs['ordinary'][0]['wer']
        release_speech_model()
        provider=TranslatorProvider('en','ar');provider.prepare()
        samples=[['But they won\'t flower','like they did last spring.'], ['Please download this video','and save the subtitles.'], ['I brought you daffodils in a pretty string.','But they won\'t flower like they did last spring.']]
        for parts in samples:
            started=time.monotonic();baseline=' '.join(provider.translate(text) for text in parts);baseline_time=time.monotonic()-started
            segments=[SimpleNamespace(start=i*2,end=i*2+2,text=text) for i,text in enumerate(parts)]
            grouped=list(sentence_groups(segments))
            started=time.monotonic();contextual=' '.join(provider.translate(s.text) for s in grouped)
            contextual_time=time.monotonic()-started
            candidate=TranslatorProvider('en','ar')
            for stage in candidate.stages:stage.length_penalty=1.0
            started=time.monotonic();candidate_text=' '.join(candidate.translate(s.text) for s in grouped);candidate_time=time.monotonic()-started
            report['translation'].append(dict(source_parts=parts,baseline=baseline,contextual=contextual,baseline_seconds=baseline_time,contextual_seconds=contextual_time,candidate_length_penalty_1=candidate_text,candidate_seconds=candidate_time,reference_ar='لكنها لن تُزهر كما أزهرت في الربيع الماضي' if 'spring' in ' '.join(parts) else 'يرجى تنزيل هذا الفيديو وحفظ الترجمة',engine='unchanged Argos/CTranslate2'))
        release_translation_models()
        video=folder/'style-source.mp4'
        run_ffmpeg(['-f','lavfi','-i','color=c=blue:s=640x360:r=15:d=2','-i',wave,'-t','2','-c:v','libx264','-c:a','aac',video])
        from local_tasks import run_local_job
        report['conversion']={}
        for mode in ('MP4','MKV','MP3','WAV'):
            result=run_local_job('Convert',video,folder/'convert','auto','ar',mode,checkpoint=lambda:None,progress=lambda *a:None,save_original=False,options=dict(codec='h264',resolution='480',bitrate='1000k'))
            streams=get_ffprobe_info(next(iter(result.values())))['streams']
            assert any(s['codec_type']=='audio' for s in streams)
            assert (any(s['codec_type']=='video' for s in streams)) == (mode in ('MP4','MKV'))
            report['conversion'][mode]=[s['codec_name'] for s in streams]
        style=dict(size_percent=3.2,color='#FFFF00',outline=.6,position='top',margin_percent=8)
        preview_subtitles(video,folder/'style-preview.png',style)
        srt=folder/'style-ar.srt';srt.write_text('1\n00:00:00,000 --> 00:00:01,900\nمعاينة الترجمة العربية دون قص الحروف\n',encoding='utf8')
        burn_subtitles(video,srt,folder/'style-burn.mp4',style=style)
        report['style_preview_and_export']=True
        report['ok']=True
    except Exception as exc:
        import traceback
        report['errors'].append(traceback.format_exc())
    finally:
        release_speech_model();release_translation_models()
    _write(folder/'media-quality-results.json',report)
    return 0 if report['ok'] else 1


def download_child(url,folder,mode):
    from main import DownloadQueueManager,DEFAULT_SETTINGS
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    manager=DownloadQueueManager(lambda:None,max_concurrent=1)
    if mode=='restore':
        manager.restore_previous()
    else:
        settings={**DEFAULT_SETTINGS,'download_dir':str(folder),'download_subs':False,'save_thumbnail':False,'quality':'Best Available (4K/HD)'}
        manager.add_task(url,settings)
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        tasks=manager.get_tasks_by_status()
        if tasks and all(t['status'] in manager.TERMINAL for t in tasks):
            _write(folder/'download-result.json',tasks)
            manager.recovery.flush();manager.shutdown()
            return 0 if all(t['status']=='Completed' for t in tasks) else 1
        time.sleep(.05)  # headless QA process, no Tk loop
    return 1


def recovery_review(media,folder):
    import http.server
    import threading
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    requests=[]
    data=Path(media).read_bytes()
    class RangeServer(http.server.BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            value=self.headers.get('Range','');requests.append(value)
            start=int(value.split('=')[1].split('-')[0]) if value.startswith('bytes=') else 0
            self.send_response(206 if value else 200)
            self.send_header('Content-Type','video/mp4');self.send_header('Accept-Ranges','bytes')
            self.send_header('Content-Length',str(len(data)-start))
            if value:self.send_header('Content-Range',f'bytes {start}-{len(data)-1}/{len(data)}')
            self.end_headers()
            try:
                for offset in range(start,len(data),8192):
                    self.wfile.write(data[offset:offset+8192]);self.wfile.flush();time.sleep(.03)
            except (BrokenPipeError,ConnectionResetError):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),RangeServer)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}/authorized.mp4'
    env=dict(os.environ,VEYORA_CONFIG_DIR=str(folder/'config'))
    def command(mode):
        base=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).with_name('main.py'))]
        return base+['--review-download-child',url,str(folder/'downloads'),mode]
    report=dict(ok=False,errors=[])
    process=None
    try:
        process=subprocess.Popen(command('start'),env=env)
        deadline=time.monotonic()+40;partials=[]
        while time.monotonic()<deadline:
            partials=list((folder/'downloads').glob('*.part'))
            if partials and partials[0].stat().st_size>32768:break
            if process.poll() is not None:raise RuntimeError('Download ended before crash test had a partial')
            time.sleep(.05)
        if not partials:raise RuntimeError('No actual yt-dlp partial produced')
        report['partial_bytes_before_kill']=partials[0].stat().st_size
        process.kill();process.wait(timeout=10)
        boundary=len(requests)
        process=subprocess.Popen(command('restore'),env=env)
        if process.wait(timeout=90):raise RuntimeError('Restarted download failed')
        tasks=json.loads((folder/'downloads'/'download-result.json').read_text(encoding='utf8'))
        output=Path(tasks[0]['downloaded_file'])
        assert len(tasks)==1 and output.read_bytes()==data
        report['requests_after_restart']=requests[boundary:]
        assert any(re.match(r'bytes=[1-9]\d*-',r) for r in requests[boundary:]),'Source did not receive a nonzero resume range'
        report.update(ok=True,task_count=len(tasks),sha256=hashlib.sha256(data).hexdigest(),actual_process_killed=True,range_resume=True)
    except Exception:
        import traceback
        report['errors'].append(traceback.format_exc())
    finally:
        if process is not None and process.poll() is None:process.kill();process.wait()
        server.shutdown();server.server_close()
    _write(folder/'recovery-results.json',report)
    return 0 if report['ok'] else 1


def gui_features_review(media,folder,stage):
    from desktop_ui import DesktopApp
    from main import SettingsManager
    from translator.video_renderer import get_ffprobe_info
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    app=DesktopApp();app.settings['ui_language']='en'
    report=dict(ok=False,errors=[],stage=stage)
    state=dict(phase='start',deadline=time.monotonic()+90)
    public='https://www.youtube.com/watch?v=VeyoraDraftTest'
    def finish(error=None):
        if error:report['errors'].append(str(error))
        report['ok']=not report['errors']
        _write(folder/('gui-features-'+stage+'.json'),report)
        app._on_close()
    def poll():
        try:
            if time.monotonic()>state['deadline']:raise RuntimeError('Actual GUI feature test timeout')
            if state['phase']=='start':
                app.show_tab('Dashboard')
                if stage=='restart':
                    assert app.url_entry.get()==public,'Public URL was not restored after real process restart'
                    report['public_link_restored']=True
                    assert app.settings['quality']=='720p (HD)'
                    app.url_entry.delete(0,'end')
                    finish();return
                app.settings['remember_public_links']=True
                app.remember_link_var.set(True)
                app.url_entry.delete(0,'end');app.url_entry.insert(0,public)
                app.quality_display_var.set(app._quality_to_display('720p (HD)'))
                for _ in range(20):
                    app.show_tab('Settings');app.show_tab('Convert');app.show_tab('Dashboard')
                    assert app.url_entry.get()==public
                report['link_survived_20_navigation_rounds']=True
                app.show_tab('Convert')
                controls=app._local_task_controls
                host=app.pages.pages['Convert']['host']
                def walk(w):
                    yield w
                    for c in w.winfo_children():yield from walk(c)
                import customtkinter as ctk
                option_values=[w.cget('values') for w in walk(host) if isinstance(w,ctk.CTkOptionMenu)]
                assert not any(any('(ar)' in x or '(en)' in x for x in values) for values in option_values)
                controls['path'].set(str(media));controls['mode'].set('WAV')
                app.selected_folder=str(folder/'converted')
                controls['start'].invoke()
                app.show_tab('Translation')
                assert app.local_tasks.snapshot('Translation') is None
                assert app.local_tasks.launch_count==1
                app.show_tab('Convert');state['phase']='convert'
            elif state['phase']=='convert' and not app.local_tasks.busy:
                task=app.local_tasks.snapshot('Convert')
                assert task.status=='completed',task.error
                streams=get_ffprobe_info(task.result['video'])['streams']
                assert [s['codec_type'] for s in streams]==['audio']
                report['actual_gui_wav_conversion']=True
                # Reopen previously downloaded cards and their disk thumbnails after process restart.
                app.queue_manager.restore_previous()
                app.show_tab('Downloads');state['phase']='thumbs'
            elif state['phase']=='thumbs':
                cards=list(app.card_widgets.values())
                if not cards or not all(getattr(c,'_thumbnail_applied',False) for c in cards):
                    app.after(50,poll);return
                report['real_thumbnails_after_restart_without_server']=True
                app.show_tab('Translation');app._local_task_controls['path'].set(str(media))
                from media_options_ui import subtitle_options
                subtitle_options(app,app._local_task_controls['path'])
                window=app._subtitle_options_window
                window._style_controls['color'].set('#FFFF00')
                window._style_controls['outline'].set('0.6')
                window._save_button.invoke();window._preview_button.invoke()
                state['phase']='preview'
            elif state['phase']=='preview':
                if hasattr(app._subtitle_options_window,'_preview_image'):
                    report['actual_gui_style_preview']=True
                    assert app.settings['subtitle_style']['color']=='#FFFF00'
                    app.show_tab('Dashboard')
                    finish();return
            app.after(50,poll)
        except Exception as exc:
            import traceback
            finish(traceback.format_exc())
    app.after(100,poll);app.mainloop()
    return 0 if report['ok'] else 1
