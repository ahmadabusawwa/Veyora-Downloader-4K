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


def _bound_segment(segment, info):
    """Whisper's final timestamp can extend beyond the decoded audio."""
    import math
    from dataclasses import is_dataclass, replace
    from types import SimpleNamespace
    duration = getattr(info, 'duration', 0) or 0
    if not math.isfinite(duration) or duration <= 0:
        return segment
    start, end = max(0, segment.start), min(duration, segment.end)
    if end <= start:
        return None
    if start == segment.start and end == segment.end:
        return segment
    if is_dataclass(segment):
        return replace(segment, start=start, end=end)
    if hasattr(segment, '_replace'):
        return segment._replace(start=start, end=end)
    values = dict(vars(segment))
    values.update(start=start, end=end)
    return SimpleNamespace(**values)


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
                    import onnxruntime
                    # VAD must never send usage telemetry, including in offline mode.
                    onnxruntime.disable_telemetry_events()
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise TranscriptionError('Install faster-whisper using requirements.txt') from exc
                root = Path(os.environ.get('VEYORA_CONFIG_DIR', str(Path.home() / '.veyora'))) / 'models'
                root.mkdir(parents=True, exist_ok=True)
                progress(f'Loading {self.language} speech model {self.model_size} (first use may download it)', None)
                # Release the old native weights before allocating a different model.
                if _model is not None:
                    _model.model.unload_model()
                    _model = None
                    _model_key = None
                options = dict(device=self.device, compute_type='int8', download_root=str(root),
                               cpu_threads=cpu_threads())
                try:
                    # A ready local cache must work without a network metadata lookup.
                    _model = WhisperModel(self.model_size, local_files_only=True, **options)
                except Exception as exc:
                    from huggingface_hub.errors import LocalEntryNotFoundError
                    if not isinstance(exc, (LocalEntryNotFoundError, FileNotFoundError)):
                        raise
                    if os.environ.get('HF_HUB_OFFLINE', '').lower() in ('1', 'true', 'yes'):
                        raise TranscriptionError('Speech model missing offline; prepare the speech model once with internet') from exc
                    checkpoint()
                    progress(f'Downloading missing speech model {self.model_size} (first use only)', None)
                    _model = WhisperModel(self.model_size, local_files_only=False, **options)
                _model_key = key
                audit = os.environ.get('VEYORA_REVIEW_AUDIT_DIR')
                if audit:
                    directory = Path(audit)
                    directory.mkdir(parents=True, exist_ok=True)
                    with (directory / 'speech-loads.jsonl').open('a', encoding='utf8') as out:
                        out.write(json.dumps(dict(pid=os.getpid(), model=self.model_size, event='speech_model_loaded')) + '\n')
            checkpoint()
            progress(f'Recognizing {self.language} speech on CPU', 0)
            target_lang = None if self.language == 'auto' else self.language
            segments, info = _model.transcribe(audio_path, language=target_lang, task='transcribe', beam_size=5, vad_filter=True, **({'vad_parameters':self.vad_parameters} if getattr(self,'vad_parameters',None) else {}))
            result = []
            for segment in segments:
                checkpoint()
                segment = _bound_segment(segment, info)
                if segment is None:
                    continue
                result.append(segment)
                duration = getattr(info, 'duration', 0) or 0
                progress(f'Recognizing {self.language} speech: {segment.end:.0f}s / {duration:.0f}s', min(1, segment.end / duration) if duration else None)
            if not result:
                # Fallback without Silero VAD when short or synthetic non-English audio is filtered out.
                checkpoint()
                try:
                    retry_segments, retry_info = _model.transcribe(
                        audio_path,
                        language=target_lang,
                        task='transcribe',
                        beam_size=5,
                        vad_filter=False,
                        no_speech_threshold=.6,
                        log_prob_threshold=-1.0,
                        condition_on_previous_text=False,
                    )
                    for segment in retry_segments:
                        checkpoint()
                        if (getattr(segment,'text','').strip() and getattr(segment,'no_speech_prob',0)<=.6
                                and getattr(segment,'avg_logprob',0)>=-1.0 and getattr(segment,'compression_ratio',0)<=2.4):
                            segment = _bound_segment(segment, retry_info)
                            if segment is not None:
                                result.append(segment)
                    if retry_info is not None:
                        info = retry_info
                except TypeError:
                    pass
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
