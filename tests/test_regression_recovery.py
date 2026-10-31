"""Regression checks; native Windows/media evidence is recorded separately."""
from pathlib import Path
from types import SimpleNamespace
import pytest


@pytest.mark.parametrize('segments', [[], [SimpleNamespace(start=0,end=1,text='  ')], [SimpleNamespace(start=1,end=1,text='Hello')]])
def test_incomplete_subtitles_never_replace_a_valid_output(tmp_path,segments):
    from translator.subtitle_generator import generate_srt
    destination=tmp_path/'نتيجة.srt';destination.write_text('existing valid output',encoding='utf8')
    with pytest.raises(ValueError):generate_srt(segments,destination)
    assert destination.read_text(encoding='utf8')=='existing valid output'
    assert not list(tmp_path.glob('*.partial'))


def test_generator_failure_preserves_prior_file(tmp_path):
    from translator.subtitle_generator import generate_srt
    destination=tmp_path/'captions.srt';destination.write_text('previous',encoding='utf8')
    def interrupted():
        yield SimpleNamespace(start=0,end=1,text='Hello')
        raise RuntimeError('Recognition interrupted')
    with pytest.raises(RuntimeError,match='interrupted'):generate_srt(interrupted(),destination)
    assert destination.read_text(encoding='utf8')=='previous'


def test_source_srt_with_a_blank_cue_is_rejected(tmp_path):
    from translator.subtitle_generator import parse_srt
    source=tmp_path/'blank.srt';source.write_text('1\n00:00:00,000 --> 00:00:01,000\n\n',encoding='utf8')
    with pytest.raises(ValueError):parse_srt(source)


def test_auto_detected_transcript_is_not_reused_for_explicit_english(monkeypatch,tmp_path):
    from translator import pipeline
    calls=[]
    class Recognizer:
        def __init__(self,language):self.language=language
        def transcribe(self,*args,**kwargs):
            calls.append(self.language)
            return [SimpleNamespace(start=0,end=1,text=self.language+' transcript')],SimpleNamespace(language='en')
    monkeypatch.setattr(pipeline,'Transcriber',Recognizer)
    monkeypatch.setattr(pipeline,'extract_audio',lambda *a:None)
    from translator import automatic_audio
    monkeypatch.setattr(automatic_audio,'audio_activity',lambda *a:None)
    monkeypatch.setattr(pipeline,'config_root',lambda:tmp_path/'config')
    media=tmp_path/'video.mp4';media.write_bytes(b'identity fixture')
    pipeline.TranslationPipeline(media,tmp_path/'out').run(source_lang='auto',target_lang='en')
    result=pipeline.TranslationPipeline(media,tmp_path/'out').run(source_lang='en',target_lang='en')
    assert calls==['auto','en']
    assert 'en transcript' in Path(result['subtitle']).read_text(encoding='utf8')


def test_empty_decoded_translation_is_a_failure(monkeypatch):
    from translator import translation_provider as module
    from translator.exceptions import TranslationError
    provider=module.DirectTranslatorProvider('en','ar')
    runtime=(SimpleNamespace(encode=lambda *a,**k:['source'],decode=lambda *a:''),
             SimpleNamespace(translate_batch=lambda *a,**k:[SimpleNamespace(hypotheses=[['piece']])]))
    monkeypatch.setitem(module._runtimes,provider.key,runtime)
    monkeypatch.setattr(provider,'prepare',lambda *a:None)
    with pytest.raises(TranslationError,match='empty'):provider.translate('Hello')
    assert not provider.cache


def test_automatic_engine_policy_and_outputs_wait_for_completion(monkeypatch,tmp_path):
    import json,time,threading
    import main,local_tasks
    from desktop_ui import DesktopApp
    from translator.subtitle_generator import generate_srt
    monkeypatch.setenv('VEYORA_CONFIG_DIR',str(tmp_path))
    monkeypatch.setattr(main,'SETTINGS_FILE',tmp_path/'settings.json')
    main.SETTINGS_FILE.write_text(json.dumps(dict(auto_update_check=False,ui_language='en')))
    entered=threading.Event();release=threading.Event();captured=[]
    def runner(*args,options,progress,checkpoint,**kwargs):
        captured.append(options);progress('Translation phase complete; validating output',1)
        entered.set();assert release.wait(3);checkpoint()
        out=tmp_path/f'output-{len(captured)}.srt'
        generate_srt([SimpleNamespace(start=0,end=1,text='مرحبا بالعالم')],out)
        return dict(subtitle=str(out))
    monkeypatch.setattr(local_tasks,'run_local_job',runner)
    app=DesktopApp()
    try:
        app.show_tab('Translation');c=app._local_task_controls
        source=tmp_path/'source.srt';source.write_text('1\n00:00:00,000 --> 00:00:01,000\nHello\n')
        c['path'].set(str(source))
        for old_policy in ('on','off'):
            app.settings.update(speech_policy=old_policy,context_policy=old_policy,enhance_speech=False,contextual_translation=False)
            entered.clear();release.clear()
            assert 'enhance_speech' not in c and 'contextual_translation' not in c
            c['start'].invoke();assert entered.wait(2);app._refresh_local_tasks(True)
            assert captured[-1]['enhance_speech']=='auto'
            assert captured[-1]['contextual_translation'] is None
            assert c['open_subtitle'].cget('state')=='disabled'
            assert c['open_folder'].cget('state')=='disabled'
            app.show_tab('Downloads');app.show_tab('Translation');assert app._local_task_controls is c
            release.set();deadline=time.monotonic()+3
            while app.local_tasks.busy and time.monotonic()<deadline:app.update();threading.Event().wait(.01)
            app._refresh_local_tasks(True)
            assert c['open_subtitle'].cget('state')=='normal'
            assert c['open_folder'].cget('state')=='normal'
            assert c['open_video'].cget('state')=='disabled' # SRT-only input does not create a video.
            assert Path(c['output_path'].get()).is_file()
    finally:release.set();app._on_close()


def test_selected_windows_language_label_is_logical_without_changing_code(monkeypatch,tmp_path):
    import main,ui_controls,json
    from desktop_ui import DesktopApp
    monkeypatch.setenv('VEYORA_CONFIG_DIR',str(tmp_path))
    monkeypatch.setattr(main,'SETTINGS_FILE',tmp_path/'settings.json')
    main.SETTINGS_FILE.write_text(json.dumps(dict(auto_update_check=False,ui_language='ar')))
    app=DesktopApp()
    try:
        monkeypatch.setattr(ui_controls,'sys',SimpleNamespace(platform='win32'))
        for code in ('auto','ar','en','tr','ko'):
            value=app._label_for_lang(code)
            app.source_menu.set(value)
            assert app._lang_code(app.source_var.get())==code
            assert app.source_menu._text_label.cget('text')==ui_controls.native_label(value)
            assert not any('\ufb50'<=character<='\ufeff' for character in app.source_menu._text_label.cget('text'))
    finally:app._on_close()


@pytest.mark.parametrize('enabled',[False,True])
def test_dialogue_option_selects_real_extraction_branch(monkeypatch,tmp_path,enabled):
    from translator.pipeline import TranslationPipeline
    from translator import pipeline,speech_enhancement
    called=[]
    monkeypatch.setattr(pipeline,'extract_audio',lambda *args:called.append('original'))
    monkeypatch.setattr(speech_enhancement,'enhance_speech',lambda *args:called.append('enhanced'))
    processor=TranslationPipeline(tmp_path/'in.mp4',tmp_path/'out')
    processor.enhance_speech=enabled
    processor._extract_speech(tmp_path/'audio.wav',lambda:None)
    assert called==['enhanced' if enabled else 'original']


def test_recovery_confirmation_is_in_app_and_no_keeps_queue(monkeypatch, tmp_path):
    """Recovery confirmation must not fall back to Windows' directionless MessageBox."""
    import main
    from tkinter import messagebox
    from desktop_ui import DesktopApp

    monkeypatch.setenv('VEYORA_CONFIG_DIR', str(tmp_path))
    monkeypatch.setattr(main, 'CONFIG_DIR', tmp_path)
    monkeypatch.setitem(main.DEFAULT_SETTINGS, 'auto_update_check', False)
    def native_dialog_not_allowed(*args, **kwargs):
        raise AssertionError('Native MessageBox must not be used for Arabic recovery')
    monkeypatch.setattr(messagebox, 'askyesno', native_dialog_not_allowed)

    app = DesktopApp()
    try:
        app.settings['ui_language'] = 'ar'
        was_restored = []
        monkeypatch.setattr(app.queue_manager, 'restore_previous',
                            lambda: was_restored.append(True))
        controls = app._offer_download_recovery()
        assert controls is app._confirm_controls
        assert controls['window'].title() == 'استعادة التحميلات'
        assert 'توجد تحميلات' in controls['label'].cget('text')
        assert controls['yes'].cget('text') == app.t('نعم', 'Yes')
        assert controls['no'].cget('text') == app.t('لا', 'No')
        controls['no'].invoke()
        assert not was_restored
        assert app._confirm_controls is None
    finally:
        app._on_close()
