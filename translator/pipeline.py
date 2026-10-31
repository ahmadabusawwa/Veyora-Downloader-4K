"""Offline translation with durable source-language transcript cache and phase progress."""
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from .transcription import Transcriber, release_speech_model
from .translation_provider import TranslatorProvider, release_translation_models
from .subtitle_generator import generate_srt
from .video_renderer import extract_audio, burn_subtitles, embed_subtitles
from .offline_model import config_root, translation_route
from .exceptions import TranscriptionError
from .resources import processing_slot


def detect_text_language(text: str) -> str | None:
    """Detect one of the 4 supported languages ('ar', 'ko', 'tr', 'en') from text script."""
    if not text or not text.strip():
        return None
    if any('\u0600' <= c <= '\u06ff' for c in text):
        return 'ar'
    if any('\uac00' <= c <= '\ud7a3' or '\u3130' <= c <= '\u318f' for c in text):
        return 'ko'
    if any(c in 'çğıöşüÇĞİÖŞÜ' for c in text):
        return 'tr'
    if re.search(r'[A-Za-z]', text):
        return 'en'
    return None


def _cache_key(media, checkpoint, source_lang='en'):
    try:
        preferred = json.loads((config_root()/'settings.json').read_text(encoding='utf8')).get('speech_model','base')
    except (OSError,ValueError,AttributeError):
        preferred = 'base'
    if preferred not in ('base','small','medium'):
        preferred = 'base'
    prefix = ('veyora-transcript-v7-auto-compare-' + preferred + '-' + source_lang + '\0').encode('ascii')
    digest = hashlib.sha256(prefix)
    with media.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            checkpoint()
            digest.update(chunk)
    return digest.hexdigest()


def _read_cache(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(value,dict):value=value.get('segments')
        if not isinstance(value, list) or not value:
            return None
        result = []
        for item in value:
            start, end, text = item['start'], item['end'], item['text']
            if not (isinstance(text, str) and text.strip() and math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
                return None
            result.append(SimpleNamespace(start=start, end=end, text=text))
        return result
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _write_cache(path, segments,coverage=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='transcript-', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(dict(schema=2,coverage=coverage,segments=[dict(start=s.start, end=s.end, text=s.text) for s in segments]), out, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _publish_file(source, destination, checkpoint):
    """Cancellable copy; an interrupted large export never becomes a final file."""
    temporary = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.partial')
    try:
        with temporary.open('xb') as out, source.open('rb') as incoming:
            while True:
                checkpoint()
                chunk = incoming.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        checkpoint()
        if destination.exists():
            raise FileExistsError(str(destination))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


class TranslationPipeline:
    def __init__(self, video_path, output_dir):
        self.video_path = Path(video_path).resolve()
        self.output_dir = Path(output_dir).resolve()

    def _review_event(self,event,**details):
        """Disposable native-test evidence only; no UI or network calls."""
        audit=os.environ.get('VEYORA_REVIEW_AUDIT_DIR')
        if audit:
            directory=Path(audit);directory.mkdir(parents=True,exist_ok=True)
            with (directory/'pipeline-events.jsonl').open('a',encoding='utf8') as stream:
                stream.write(json.dumps(dict(event=event,**details),ensure_ascii=False)+'\n')

    def run(self, mode='separate', checkpoint=lambda: None, progress=lambda stage, fraction=None: None, source_lang='en', target_lang='ar', save_original=True, subtitle_style=None, enhance_speech=None, contextual_translation=None, output_container="mkv"):
        if output_container not in ('mp4','mkv'):
            raise ValueError('Unsupported output container')
        self.output_container = output_container
        self._auto_detected_input=False
        self.coverage_review=None
        from .recognition_policy import should_enhance,speech_mode
        self.speech_policy=speech_mode(enhance_speech)
        self.enhance_speech = should_enhance(enhance_speech)
        self.contextual_translation = contextual_translation
        self.subtitle_style = subtitle_style
        with processing_slot(checkpoint, progress):
            try:
                return self._run(mode, checkpoint, progress, source_lang, target_lang, save_original)
            finally:
                release_speech_model()
                release_translation_models()

    def _finish_outputs(self, temp, stem, target_lang, target_name, segments, mode, checkpoint, progress, outputs):
        subtitle = temp / 'captions.srt'
        generate_srt(segments, subtitle)
        checkpoint()
        destination = self.output_dir / (stem + '.' + target_lang + '.srt')
        _publish_file(subtitle, destination, checkpoint)
        outputs['subtitle'] = str(destination)
        if mode in ('embed', 'both', 'burn'):
            progress(f'Burning {target_name} subtitles' if mode == 'burn' else f'Embedding {target_name} subtitle track', None)
            rendered = temp / ('rendered.mp4' if mode == 'burn' else 'rendered.'+getattr(self,'output_container','mkv'))
            renderer = burn_subtitles if mode == 'burn' else embed_subtitles
            def render_progress(fraction, eta, speed):
                action = 'Burning' if mode == 'burn' else 'Embedding'
                text = f'{action} {target_name} subtitles'
                if fraction is not None:
                    text += f': {fraction*100:.1f}%'
                if speed is not None:
                    text += f' | {speed:.2f}x'
                if eta is not None:
                    minutes, seconds = divmod(int(eta), 60)
                    hours, minutes = divmod(minutes, 60)
                    text += f' | ETA ~{hours:02}:{minutes:02}:{seconds:02}'
                else:
                    text += ' | ETA estimating'
                progress(text, fraction)
            if mode == 'burn':
                renderer(self.video_path, subtitle, rendered, checkpoint, progress=render_progress, **({'style': self.subtitle_style} if getattr(self, 'subtitle_style', None) else {}))
            else:
                renderer(self.video_path, subtitle, rendered, checkpoint, subtitle_lang=target_lang, progress=render_progress)
            checkpoint()
            progress('Saving completed video to output folder', None)
            target = self.output_dir / (stem + '.' + target_lang + rendered.suffix)
            _publish_file(rendered, target, checkpoint)
            outputs['video'] = str(target)
        if getattr(self,'coverage_review',None):
            report=self.output_dir/(stem+'.coverage.json')
            report.write_text(json.dumps(self.coverage_review,ensure_ascii=False,indent=2),encoding='utf8')
            outputs['coverage_report']=str(report)
        return outputs

    def _run(self, mode, checkpoint, progress, source_lang, target_lang, save_original=False):
        if self.video_path.suffix.lower() == '.srt':
            return self._translate_srt(source_lang, target_lang, checkpoint, progress)
        if mode not in ('separate', 'embed', 'burn', 'both'):
            raise ValueError('Unknown subtitle output mode')
        if source_lang == 'auto':
            self._auto_detected_input=True
            with tempfile.TemporaryDirectory(prefix='veyora-detect-') as folder:
                audio = Path(folder) / 'speech.wav'
                self._extract_speech(audio, checkpoint)
                detected_segments, info = self._recognize(audio,'auto',checkpoint,progress)
                detected = getattr(info, 'language', None)
                if detected not in ('ar', 'en', 'tr', 'ko') and detected_segments:
                    detected = detect_text_language(' '.join(s.text for s in detected_segments))
                if detected not in ('ar', 'en', 'tr', 'ko'):
                    raise TranscriptionError('Detected speech language is not supported')
                if detected_segments:
                    cache = config_root() / 'transcripts' / (_cache_key(self.video_path, checkpoint, detected + '-auto-detected' + ('-speech-'+getattr(self,'speech_policy','off'))) + '.json')
                    _write_cache(cache, detected_segments,self.coverage_review)
                release_speech_model()
                if detected == target_lang:
                    if not detected_segments:
                        raise TranscriptionError('Detected source equals target; choose a different target language')
                    self.output_dir.mkdir(parents=True, exist_ok=True)
                    stem = self.video_path.stem + '.' + uuid.uuid4().hex[:12]
                    target_name = {'ar': 'Arabic', 'en': 'English', 'tr': 'Turkish', 'ko': 'Korean'}[target_lang]
                    return self._finish_outputs(Path(folder), stem, target_lang, target_name, detected_segments, mode, checkpoint, progress, {})
            return self._run(mode, checkpoint, progress, detected, target_lang, save_original)
        if source_lang != target_lang:
            translation_route(source_lang, target_lang)
        elif source_lang not in ('ar', 'en', 'tr', 'ko'):
            raise ValueError('Unsupported source language')
        source_name = {'ar': 'Arabic', 'en': 'English', 'tr': 'Turkish', 'ko': 'Korean'}[source_lang]
        target_name = {'ar': 'Arabic', 'en': 'English', 'tr': 'Turkish', 'ko': 'Korean'}[target_lang]
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stem = self.video_path.stem + '.' + uuid.uuid4().hex[:12]
        outputs = {}
        progress(f'Checking saved {source_name} transcript', None)
        cache = config_root() / 'transcripts' / (_cache_key(self.video_path, checkpoint, source_lang + ('-auto-detected' if getattr(self,'_auto_detected_input',False) else '') + ('-speech-'+getattr(self,'speech_policy','off'))) + '.json')
        segments = _read_cache(cache)
        if segments is not None:
            saved=json.loads(cache.read_text(encoding='utf8'))
            if isinstance(saved,dict):self.coverage_review=saved.get('coverage')
        with tempfile.TemporaryDirectory(prefix='veyora-translate-') as temp:
            temp = Path(temp)
            checkpoint()
            if segments is None:
                progress('Extracting audio', None)
                audio = temp / 'speech.wav'
                self._extract_speech(audio, checkpoint)
                segments, _ = self._recognize(audio,source_lang,checkpoint,progress)
                if not segments:
                    raise TranscriptionError(f'No {source_name} speech was detected; no subtitle was produced')
                _write_cache(cache, segments,self.coverage_review)
                release_speech_model()
            else:
                progress(f'Using saved {source_name} transcript (no repeated speech recognition)', 1)
            english = self.output_dir / (stem + '.' + source_lang + '.srt')
            if save_original and source_lang != target_lang:
                generate_srt(segments, english)
                outputs['source_subtitle'] = str(english)
            if source_lang == target_lang:
                translated = segments
            else:
                translator = TranslatorProvider(source_lang, target_lang)
                translator.prepare(checkpoint, progress)
                translated = []
                original_cues=len(segments)
                if getattr(self,'contextual_translation',None) is not False:
                    from .context_segments import sentence_groups
                    from .recognition_policy import automatic_context
                    segments = list(sentence_groups(segments) if self.contextual_translation is True or self.contextual_translation=='on' else automatic_context(segments))
                self._review_event('translation_context',policy=self.contextual_translation,input_cues=original_cues,translated_cues=len(segments))
                for index, segment in enumerate(segments):
                    checkpoint()
                    progress(f'Translating locally: subtitle {index + 1}/{len(segments)}', index / len(segments))
                    text = translator.translate(segment.text, checkpoint=checkpoint)
                    translated.append(SimpleNamespace(start=segment.start, end=segment.end, text=text))
                progress(f'{target_name} translation complete: {len(segments)}/{len(segments)}', 1)
                translator.cache.clear()
                release_translation_models()
            return self._finish_outputs(temp, stem, target_lang, target_name, translated, mode, checkpoint, progress, outputs)

    def _recognize(self,audio,language,checkpoint,progress):
        original,info=Transcriber(language=language).transcribe(str(audio),checkpoint=checkpoint,progress=progress)
        if getattr(self,'speech_policy','off')!='auto':return original,info
        from .automatic_audio import audio_activity,needs_candidate,prefer_candidate
        activity=audio_activity(audio)
        selected=original;selected_info=info;attempted=False;accepted=False
        if needs_candidate(original,activity):
            checkpoint();attempted=True
            progress('Comparing original audio with dialogue enhancement',None)
            candidate_audio=Path(audio).with_name('dialogue-candidate.wav')
            try:
                from .speech_enhancement import enhance_speech
                enhance_speech(self.video_path,candidate_audio,checkpoint)
                candidate,candidate_info=Transcriber(language=language).transcribe(str(candidate_audio),checkpoint=checkpoint,progress=progress)
                # Auto detection must not silently switch the language based on a
                # processed candidate. Keep the original if the passes disagree.
                languages_match=getattr(info,'language',None)==getattr(candidate_info,'language',None)
                accepted=languages_match and prefer_candidate(original,candidate)
                if accepted:selected,selected_info=candidate,candidate_info
                self._review_event('audio_candidate',accepted=accepted,original=[dict(start=s.start,end=s.end,text=s.text) for s in original],candidate=[dict(start=s.start,end=s.end,text=s.text) for s in candidate])
            except Exception as exc:
                checkpoint() # Cancellation always propagates; failed enhancement keeps original.
                from runtime_support import log_failure
                log_failure(exc,'optional dialogue candidate; original retained')
        last=max((s.end for s in selected),default=0)
        if activity and any(s.start<0 or s.end>activity['duration']+.05 or s.end<=s.start for s in selected):
            raise TranscriptionError('Recognized timestamps exceed the extracted audio timeline')
        tail=sum(t>last+2 for t in activity['active_seconds']) if activity else 0
        if tail>=8:
            self.coverage_review=dict(status='REVIEW REQUIRED',audio_duration=activity['duration'],last_recognized_end=last,
                reason='Audible audio continues after the transcript. This may be music or missed vocals; speech coverage is not verified.',
                enhancement_attempted=attempted,enhancement_selected=accepted)
        self._review_event('automatic_dialogue',attempted=attempted,accepted=accepted,
            last_recognized_end=max((s.end for s in selected),default=0),audio_duration=activity['duration'] if activity else None,
            note='Energy/confidence heuristics are not evidence that every vocal was recognized')
        return selected,selected_info

    def _extract_speech(self, output, checkpoint):
        if getattr(self,'enhance_speech',False):
            from .speech_enhancement import enhance_speech
            enhance_speech(self.video_path, output, checkpoint)
        else:
            extract_audio(self.video_path, output, checkpoint)
        if os.environ.get('VEYORA_REVIEW_AUDIT_DIR'):
            with Path(output).open('rb') as audio:digest=hashlib.file_digest(audio,'sha256').hexdigest()
            preserved=Path(os.environ['VEYORA_REVIEW_AUDIT_DIR'])/('audio-'+uuid.uuid4().hex+'.wav')
            preserved.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(output,preserved)
            self._review_event('audio_extraction',enhanced=bool(getattr(self,'enhance_speech',False)),audio_sha256=digest,audio_file=preserved.name)

    def _translate_srt(self, source_lang, target_lang, checkpoint, progress):
        from .subtitle_generator import parse_srt
        segments = parse_srt(self.video_path)
        if source_lang == 'auto':
            inferred = detect_text_language(' '.join(s.text for s in segments))
            if not inferred:
                raise ValueError('Select the source language for SRT text')
            source_lang = inferred
        if source_lang == target_lang and source_lang in ('ar', 'en', 'tr', 'ko'):
            self.output_dir.mkdir(parents=True, exist_ok=True)
            output = self.output_dir / (self.video_path.stem + '.' + uuid.uuid4().hex[:12] + '.' + target_lang + '.srt')
            generate_srt(segments, output)
            return {'subtitle': str(output)}
        translation_route(source_lang, target_lang)
        translator = TranslatorProvider(source_lang, target_lang)
        translator.prepare(checkpoint, progress)
        result = []
        if getattr(self,'contextual_translation',None) is not False:
            from .context_segments import sentence_groups
            from .recognition_policy import automatic_context
            segments = list(sentence_groups(segments) if self.contextual_translation is True or self.contextual_translation=='on' else automatic_context(segments))
        for i, segment in enumerate(segments):
            checkpoint()
            result.append(SimpleNamespace(start=segment.start, end=segment.end, text=translator.translate(segment.text, checkpoint=checkpoint)))
            progress('Translating SRT', (i+1)/len(segments))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output = self.output_dir / (self.video_path.stem + '.' + uuid.uuid4().hex[:12] + '.' + target_lang + '.srt')
        generate_srt(result, output)
        return {'subtitle': str(output)}
