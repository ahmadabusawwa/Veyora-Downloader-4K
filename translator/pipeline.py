"""Offline translation with durable source-language transcript cache and phase progress."""
import hashlib
import json
import math
import os
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


def _cache_key(media, checkpoint, source_lang='en'):
    prefix = ('veyora-base-v2-' + source_lang + '\0').encode('ascii')
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


class TranslationPipeline:
    def __init__(self, video_path, output_dir):
        self.video_path = Path(video_path).resolve()
        self.output_dir = Path(output_dir).resolve()

    def run(self, mode='separate', checkpoint=lambda: None, progress=lambda stage, fraction=None: None, source_lang='en', target_lang='ar', save_original=True):
        with processing_slot(checkpoint, progress):
            try:
                return self._run(mode, checkpoint, progress, source_lang, target_lang, save_original)
            finally:
                release_speech_model()
                release_translation_models()

    def _run(self, mode, checkpoint, progress, source_lang, target_lang, save_original=False):
        if self.video_path.suffix.lower() == '.srt':
            return self._translate_srt(source_lang, target_lang, checkpoint, progress)
        if source_lang == 'auto':
            with tempfile.TemporaryDirectory(prefix='veyora-detect-') as folder:
                audio = Path(folder) / 'speech.wav'
                extract_audio(self.video_path, audio, checkpoint)
                detected_segments, info = Transcriber(language='auto').transcribe(str(audio), checkpoint, progress)
                detected = getattr(info, 'language', None)
                if detected not in ('ar', 'en', 'tr', 'ko'):
                    raise TranscriptionError('Detected speech language is not supported')
                if detected == target_lang:
                    raise TranscriptionError('Detected source equals target; choose a different target language')
                cache = config_root() / 'transcripts' / (_cache_key(self.video_path, checkpoint, detected) + '.json')
                _write_cache(cache, detected_segments)
                release_speech_model()
            return self._run(mode, checkpoint, progress, detected, target_lang, save_original)
        translation_route(source_lang, target_lang)
        source_name = {'ar': 'Arabic', 'en': 'English', 'tr': 'Turkish', 'ko': 'Korean'}[source_lang]
        target_name = {'ar': 'Arabic', 'en': 'English', 'tr': 'Turkish', 'ko': 'Korean'}[target_lang]
        if mode not in ('separate', 'embed', 'burn', 'both'):
            raise ValueError('Unknown subtitle output mode')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stem = self.video_path.stem + '.' + uuid.uuid4().hex[:12]
        outputs = {}
        progress(f'Checking saved {source_name} transcript', None)
        cache = config_root() / 'transcripts' / (_cache_key(self.video_path, checkpoint, source_lang) + '.json')
        segments = _read_cache(cache)
        with tempfile.TemporaryDirectory(prefix='veyora-translate-') as temp:
            temp = Path(temp)
            checkpoint()
            if segments is None:
                progress('Extracting audio', None)
                audio = temp / 'speech.wav'
                extract_audio(self.video_path, audio, checkpoint)
                segments, _ = Transcriber(language=source_lang).transcribe(str(audio), checkpoint=checkpoint, progress=progress)
                if not segments:
                    raise TranscriptionError(f'No {source_name} speech was detected; no subtitle was produced')
                _write_cache(cache, segments)
                release_speech_model()
            else:
                progress(f'Using saved {source_name} transcript (no repeated speech recognition)', 1)
            english = self.output_dir / (stem + '.' + source_lang + '.srt')
            if save_original:
                generate_srt(segments, english)
                outputs['source_subtitle'] = str(english)
            translator = TranslatorProvider(source_lang, target_lang)
            translator.prepare(checkpoint, progress)
            translated = []
            for index, segment in enumerate(segments):
                checkpoint()
                progress(f'Translating locally: subtitle {index + 1}/{len(segments)}', index / len(segments))
                text = translator.translate(segment.text, checkpoint=checkpoint)
                translated.append(SimpleNamespace(start=segment.start, end=segment.end, text=text))
            progress(f'{target_name} translation complete: {len(segments)}/{len(segments)}', 1)
            translator.cache.clear()
            release_translation_models()
            subtitle = temp / 'captions.srt'
            generate_srt(translated, subtitle)
            checkpoint()
            destination = self.output_dir / (stem + '.' + target_lang + '.srt')
            with destination.open('xb') as stream:
                stream.write(subtitle.read_bytes())
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
                    renderer(self.video_path, subtitle, rendered, checkpoint, progress=render_progress)
                else:
                    renderer(self.video_path, subtitle, rendered, checkpoint, subtitle_lang=target_lang, progress=render_progress)
                checkpoint()
                progress('Saving completed video to output folder', None)
                target = self.output_dir / (stem + '.' + target_lang + rendered.suffix)
                with target.open('xb') as stream, rendered.open('rb') as source:
                    shutil.copyfileobj(source, stream)
                outputs['video'] = str(target)
        return outputs

    def _translate_srt(self, source_lang, target_lang, checkpoint, progress):
        if source_lang == 'auto':
            raise ValueError('Select the source language for SRT text')
        translation_route(source_lang, target_lang)
        from .subtitle_generator import parse_srt
        segments = parse_srt(self.video_path)
        translator = TranslatorProvider(source_lang, target_lang)
        translator.prepare(checkpoint, progress)
        result = []
        for i, segment in enumerate(segments):
            checkpoint()
            result.append(SimpleNamespace(start=segment.start, end=segment.end, text=translator.translate(segment.text, checkpoint=checkpoint)))
            progress('Translating SRT', (i+1)/len(segments))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output = self.output_dir / (self.video_path.stem + '.' + uuid.uuid4().hex[:12] + '.' + target_lang + '.srt')
        generate_srt(result, output)
        return {'subtitle': str(output)}
