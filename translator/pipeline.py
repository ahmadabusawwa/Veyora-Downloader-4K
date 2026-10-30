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
    prefix = ('veyora-base-v3-bounded-' + source_lang + '\0').encode('ascii')
    digest = hashlib.sha256(prefix)
    with media.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            checkpoint()
            digest.update(chunk)
    return digest.hexdigest()


def _read_cache(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, list) or not value:
            return None
        result = []
        for item in value:
            start, end, text = item['start'], item['end'], item['text']
            if not (isinstance(text, str) and math.isfinite(start) and math.isfinite(end) and 0 <= start <= end):
                return None
            result.append(SimpleNamespace(start=start, end=end, text=text))
        return result
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _write_cache(path, segments):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='transcript-', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump([dict(start=s.start, end=s.end, text=s.text) for s in segments], out, ensure_ascii=False)
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

    def run(self, mode='separate', checkpoint=lambda: None, progress=lambda stage, fraction=None: None, source_lang='en', target_lang='ar', save_original=True, subtitle_style=None, enhance_speech=False, contextual_translation=False):
        self.enhance_speech = bool(enhance_speech)
        self.contextual_translation = bool(contextual_translation)
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
            rendered = temp / ('rendered.mp4' if mode == 'burn' else 'rendered.mkv')
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
        return outputs

    def _run(self, mode, checkpoint, progress, source_lang, target_lang, save_original=False):
        if self.video_path.suffix.lower() == '.srt':
            return self._translate_srt(source_lang, target_lang, checkpoint, progress)
        if mode not in ('separate', 'embed', 'burn', 'both'):
            raise ValueError('Unknown subtitle output mode')
        if source_lang == 'auto':
            with tempfile.TemporaryDirectory(prefix='veyora-detect-') as folder:
                audio = Path(folder) / 'speech.wav'
                self._extract_speech(audio, checkpoint)
                detected_segments, info = Transcriber(language='auto').transcribe(str(audio), checkpoint, progress)
                detected = getattr(info, 'language', None)
                if detected not in ('ar', 'en', 'tr', 'ko') and detected_segments:
                    detected = detect_text_language(' '.join(s.text for s in detected_segments))
                if detected not in ('ar', 'en', 'tr', 'ko'):
                    raise TranscriptionError('Detected speech language is not supported')
                if detected_segments:
                    cache = config_root() / 'transcripts' / (_cache_key(self.video_path, checkpoint, detected + ('-enhance-v1' if getattr(self,'enhance_speech',False) else '')) + '.json')
                    _write_cache(cache, detected_segments)
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
        cache = config_root() / 'transcripts' / (_cache_key(self.video_path, checkpoint, source_lang + ('-enhance-v1' if getattr(self,'enhance_speech',False) else '')) + '.json')
        segments = _read_cache(cache)
        with tempfile.TemporaryDirectory(prefix='veyora-translate-') as temp:
            temp = Path(temp)
            checkpoint()
            if segments is None:
                progress('Extracting audio', None)
                audio = temp / 'speech.wav'
                self._extract_speech(audio, checkpoint)
                segments, _ = Transcriber(language=source_lang).transcribe(str(audio), checkpoint=checkpoint, progress=progress)
                if not segments:
                    raise TranscriptionError(f'No {source_name} speech was detected; no subtitle was produced')
                _write_cache(cache, segments)
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
                if getattr(self,'contextual_translation',False):
                    from .context_segments import sentence_groups
                    segments = list(sentence_groups(segments))
                for index, segment in enumerate(segments):
                    checkpoint()
                    progress(f'Translating locally: subtitle {index + 1}/{len(segments)}', index / len(segments))
                    text = translator.translate(segment.text, checkpoint=checkpoint)
                    translated.append(SimpleNamespace(start=segment.start, end=segment.end, text=text))
                progress(f'{target_name} translation complete: {len(segments)}/{len(segments)}', 1)
                translator.cache.clear()
                release_translation_models()
            return self._finish_outputs(temp, stem, target_lang, target_name, translated, mode, checkpoint, progress, outputs)

    def _extract_speech(self, output, checkpoint):
        if getattr(self,'enhance_speech',False):
            from .speech_enhancement import enhance_speech
            enhance_speech(self.video_path, output, checkpoint)
        else:
            extract_audio(self.video_path, output, checkpoint)

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
        if getattr(self,'contextual_translation',False):
            from .context_segments import sentence_groups
            segments = list(sentence_groups(segments))
        for i, segment in enumerate(segments):
            checkpoint()
            result.append(SimpleNamespace(start=segment.start, end=segment.end, text=translator.translate(segment.text, checkpoint=checkpoint)))
            progress('Translating SRT', (i+1)/len(segments))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output = self.output_dir / (self.video_path.stem + '.' + uuid.uuid4().hex[:12] + '.' + target_lang + '.srt')
        generate_srt(result, output)
        return {'subtitle': str(output)}
