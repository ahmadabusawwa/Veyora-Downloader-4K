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


def _original_music(path):
    """Original synthesized stereo melody/percussion across the speech band."""
    import numpy as np
    import wave
    rate=16000
    timebase=np.arange(rate*30)/rate
    beat=np.floor(timebase*4).astype(int)
    envelope=np.exp(-7*(timebase*4-beat))
    notes=np.array([440,523.251,659.255,587.33,493.883,698.456,659.255,523.251])
    channels=[]
    for shift in (0,3):
        frequency=notes[(beat+shift)%len(notes)]
        signal=sum(np.sin(2*np.pi*frequency*timebase*harmonic)/harmonic**1.3 for harmonic in range(1,9))
        signal=signal*envelope
        rng=np.random.default_rng(41+shift)
        hat=rng.standard_normal(len(timebase))*.07*np.exp(-25*(timebase*4-beat))
        channels.append(signal+hat)
    music=np.stack(channels,axis=1)
    music=music/max(1,float(np.max(np.abs(music))))*.95
    with wave.open(str(path),'wb') as stream:
        stream.setnchannels(2);stream.setsampwidth(2);stream.setframerate(rate)
        stream.writeframes((music*32767).astype('<i2').tobytes())


def quality_review(wave,folder):
    if os.environ.get('VEYORA_REVIEW_NETWORK_BLOCKED') != '1':
        raise RuntimeError('Native quality tests require verified firewall isolation')
    from translator.transcription import Transcriber,release_speech_model
    from translator.translation_provider import TranslatorProvider,release_translation_models
    from translator.video_renderer import extract_audio,run_ffmpeg,preview_subtitles,get_ffprobe_info,burn_subtitles
    from translator.speech_enhancement import enhance_speech
    from translator.recognition_policy import automatic_context as sentence_groups
    from types import SimpleNamespace
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    report=dict(ok=False,errors=[],recognition=[],translation=[],limitations=['Synthetic SAPI speech and synthesized accompaniment; human singing accuracy has not been verified.','Center enhancement is not neural separation and cannot recover all speech under music.'])
    reference='Hello world. Today the weather is beautiful. Please download this video and save the subtitles.'
    try:
        _original_music(folder/'original-music.wav')
        extract_audio(wave,folder/'reference-16k.wav')
        import wave as wav_reader
        import numpy as np
        import math
        def rms(path):
            with wav_reader.open(str(path),'rb') as audio:
                samples=np.frombuffer(audio.readframes(audio.getnframes()),dtype='<i2').astype(float)/32768
                samples=samples.reshape(-1,audio.getnchannels()).mean(axis=1)
                return float(np.sqrt(np.mean(samples*samples)))
        report['mixture_speech_to_music_rms_db']=20*math.log10(max(1e-9,rms(folder/'reference-16k.wav')*.35)/max(1e-9,rms(folder/'original-music.wav')*.8))
        recognizer=Transcriber(language='en')
        for name in ('ordinary','light_music','loud_music','quiet_speech','pitch_modulated_vocal','sound_effects'):
            media=folder/(name+'.wav')
            if name=='sound_effects':
                run_ffmpeg(['-i',wave,'-f','lavfi','-i','anoisesrc=color=white:amplitude=0.9:sample_rate=16000:duration=30:seed=17',
                    '-filter_complex',"[0:a]volume=0.35[s];[1:a]volume='if(lt(mod(t,3),0.3),1,0)':eval=frame[n];[s][n]amix=inputs=2:duration=first:normalize=0[out]",'-map','[out]',media])
            elif name in ('ordinary','quiet_speech'):
                import shutil
                if name=='ordinary':shutil.copyfile(wave,media)
                else:run_ffmpeg(['-i',wave,'-af','volume=0.015',media])
            else:
                # Known reference speech; deterministic original accompaniment, not downloaded copyrighted music.
                speech_filter='[0:a]aformat=channel_layouts=stereo,volume=0.35[s];'
                if name=='pitch_modulated_vocal':
                    speech_filter='[0:a]vibrato=f=5:d=0.6,aformat=channel_layouts=stereo,volume=0.35[s];'
                music_gain='0.08' if name=='light_music' else '0.8'
                run_ffmpeg(['-i',wave,'-i',folder/'original-music.wav',
                    '-filter_complex',speech_filter+f'[1:a]volume={music_gain}[m];[s][m]amix=inputs=2:duration=first:normalize=0[out]', '-map','[out]',media])
            for enhanced in (False,True):
                audio=folder/(name+('-enhanced' if enhanced else '-baseline')+'.wav')
                started=time.monotonic()
                (enhance_speech if enhanced else extract_audio)(media,audio)
                segments,_=recognizer.transcribe(str(audio))
                text=' '.join(s.text.strip() for s in segments)
                from navigation_validation import memory_bytes
                report['recognition'].append(dict(sample=name,enhanced=enhanced,reference=reference,text=text,wer=wer(reference,text),seconds=round(time.monotonic()-started,3),working_set_bytes=memory_bytes()))
        # Exercise the integrated selection policy on the same real samples.
        from translator.pipeline import TranslationPipeline
        report['automatic_policy']=[]
        for name in ('ordinary','loud_music','sound_effects','pitch_modulated_vocal'):
            processor=TranslationPipeline(folder/(name+'.wav'),folder/'auto')
            processor.speech_policy='auto';processor.enhance_speech=False
            segments,_=processor._recognize(folder/(name+'-baseline.wav'),'en',lambda:None,lambda *args:None)
            text=' '.join(s.text.strip() for s in segments)
            baseline=next(r for r in report['recognition'] if r['sample']==name and not r['enhanced'])
            report['automatic_policy'].append(dict(sample=name,text=text,wer=wer(reference,text),original_wer=baseline['wer']))
        report['automatic_policy_regression_detected']=any(r['wer']>r['original_wer'] for r in report['automatic_policy'])
        pairs={name:[r for r in report['recognition'] if r['sample']==name] for name in ('ordinary','loud_music','pitch_modulated_vocal')}
        report['speech_improvement_verified_on_fixture'] = pairs['loud_music'][1]['wer'] < pairs['loud_music'][0]['wer'] and pairs['ordinary'][1]['wer'] <= pairs['ordinary'][0]['wer']
        release_speech_model()
        from translator import benchmark_reference
        old_recognizer=benchmark_reference.Transcriber(language='en')
        report['asr_before_after']=[]
        for name in ('ordinary','light_music','loud_music','quiet_speech','pitch_modulated_vocal','sound_effects'):
            started=time.monotonic();segments,_=old_recognizer.transcribe(str(folder/(name+'-baseline.wav')))
            text=' '.join(s.text.strip() for s in segments)
            after=next(row for row in report['recognition'] if row['sample']==name and not row['enhanced'])
            report['asr_before_after'].append(dict(sample=name,before_commit='ffd9c5960afc732bf1502352c1e29a5870176dbd',before_text=text,before_wer=wer(reference,text),after_text=after['text'],after_wer=after['wer'],before_seconds=round(time.monotonic()-started,3),after_seconds=after['seconds'],working_set_before_bytes=memory_bytes(),working_set_after_bytes=after['working_set_bytes']))
        report['asr_regression_detected']=any(r['after_wer']>r['before_wer'] for r in report['asr_before_after'])
        benchmark_reference.release_speech_model()
        # Evaluate softer VAD separately; never adopt it without lower WER and a hallucination check.
        recognizer.vad_parameters={'threshold':.35,'speech_pad_ms':400,'min_speech_duration_ms':100}
        report['soft_vad_candidate']=[]
        for name in ('ordinary','light_music','loud_music','quiet_speech'):
            started=time.monotonic();segments,_=recognizer.transcribe(str(folder/(name+'-baseline.wav')))
            text=' '.join(s.text.strip() for s in segments)
            report['soft_vad_candidate'].append(dict(sample=name,text=text,wer=wer(reference,text),seconds=round(time.monotonic()-started,3)))
        del recognizer.vad_parameters
        music_only=folder/'music-only-16k.wav';extract_audio(folder/'original-music.wav',music_only)
        segments,_=recognizer.transcribe(str(music_only))
        report['music_only_text']=' '.join(s.text.strip() for s in segments)
        report['music_only_hallucination_detected']=bool(report['music_only_text'])
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
        if report.get('automatic_policy_regression_detected'):
            raise RuntimeError('Automatic dialogue policy regressed against the original audio reference')
        if report.get('asr_regression_detected'):
            raise RuntimeError('ASR reference comparison detected a regression; do not deliver as accepted')
        if report.get('music_only_hallucination_detected'):
            raise RuntimeError('ASR returned words for the music-only control; quality acceptance failed')
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
                if stage in ('disabled','empty'):
                    assert app.url_entry.get()=='','An old URL was restored against the saved preference/empty draft'
                    assert 'Beautiful Nature' not in app.preview_title.cget('text')
                    report['empty_url_has_no_stale_metadata']=True
                    report['completed_history_count']=len(app.queue_manager.get_tasks_by_status('completed'))
                    app.settings['remember_public_links']=True
                    finish();return
                if stage=='restart':
                    assert app.url_entry.get()==public,'Public URL was not restored after real process restart'
                    report['public_link_restored']=True
                    assert app.settings['quality']=='720p (HD)'
                    assert 'Beautiful Nature' not in app.preview_title.cget('text')
                    report['restored_link_has_no_fake_analysis']=True
                    app.settings['remember_public_links']=False
                    app.remember_link_var.set(False)
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
