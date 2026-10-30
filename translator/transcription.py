from pathlib import Path
import os
import json
from performance import cpu_threads
import threading
from .exceptions import TranscriptionError

# Avoid loading several model copies when downloads finish together.
_model = None
_model_key = None
_model_lock = threading.Lock()


class Transcriber:
    def __init__(self, model_size=None, device='cpu', language='en'):
        if language not in ('auto', 'en', 'ar', 'tr', 'ko'):
            raise TranscriptionError('Select English, Arabic, Turkish or Korean as the speech language')
        self.language = language
        if model_size is None:
            try:
                root=Path(os.environ.get('VEYORA_CONFIG_DIR',str(Path.home()/'.veyora')))
                preferred=json.loads((root/'settings.json').read_text(encoding='utf8')).get('speech_model','base')
            except (OSError,ValueError,AttributeError):preferred='base'
            if preferred not in ('base','small','medium'):preferred='base'
            model_size = 'base.en' if language=='en' and preferred=='base' else preferred
        self.model_size = model_size
        if language != 'en' and self.model_size.endswith('.en'):
            raise TranscriptionError('Non-English speech requires a multilingual Whisper model')
        self.device = device

    def transcribe(self, audio_path, checkpoint=lambda: None, progress=lambda stage, fraction=None: None):
        global _model, _model_key
        progress('Waiting for speech recognizer', None)
        while not _model_lock.acquire(timeout=0.1):
            checkpoint()
        try:
            checkpoint()
            key = (self.model_size, self.device)
            if _model is None or (_model_key is not None and _model_key != key):
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise TranscriptionError('Install faster-whisper using requirements.txt') from exc
                root = Path(os.environ.get('VEYORA_CONFIG_DIR', str(Path.home() / '.veyora'))) / 'models'
                root.mkdir(parents=True, exist_ok=True)
                progress(f'Loading {self.language} speech model {self.model_size} (first use may download it)', None)
                _model = WhisperModel(self.model_size, device=self.device, compute_type='int8', download_root=str(root), cpu_threads=cpu_threads())
                _model_key = key
            checkpoint()
            progress(f'Recognizing {self.language} speech on CPU', 0)
            segments, info = _model.transcribe(audio_path, language=None if self.language == 'auto' else self.language, task='transcribe', beam_size=5, vad_filter=True)
            result = []
            for segment in segments:
                checkpoint()
                result.append(segment)
                duration = getattr(info, 'duration', 0) or 0
                progress(f'Recognizing {self.language} speech: {segment.end:.0f}s / {duration:.0f}s', min(1, segment.end / duration) if duration else None)
            return result, info
        finally:
            _model_lock.release()


def release_speech_model():
    """Release native model memory after transcription, before text translation/render."""
    import gc
    global _model, _model_key
    with _model_lock:
        if _model is not None:
            _model.model.unload_model()
            _model = None
            _model_key = None
    gc.collect()
