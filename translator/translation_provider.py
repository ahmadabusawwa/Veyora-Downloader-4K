"""Offline subtitle translation using an Argos model and CTranslate2 CPU inference."""
import os
from performance import cpu_threads
import threading
from .exceptions import TranslationError
from .offline_model import ensure_model, model_entry, translation_route

_runtimes = {}
_runtime_lock = threading.Lock()


class DirectTranslatorProvider:
    def __init__(self, source_lang='en', target_lang='ar'):
        model_entry(source_lang, target_lang)
        self.source_lang, self.target_lang = source_lang, target_lang
        self.key = (source_lang, target_lang)
        self.cache = {}

    def prepare(self, checkpoint=lambda: None, progress=lambda stage, fraction=None: None):
        if self.key in _runtimes:
            return
        directory = ensure_model(checkpoint, progress, self.source_lang, self.target_lang)
        while not _runtime_lock.acquire(timeout=.1):
            checkpoint()
        try:
            if self.key not in _runtimes:
                checkpoint()
                progress(f'Loading local {self.source_lang} -> {self.target_lang} translator on CPU', None)
                import ctranslate2
                import sentencepiece
                tokenizer = sentencepiece.SentencePieceProcessor(model_file=str(directory / 'sentencepiece.model'))
                translator = ctranslate2.Translator(str(directory / 'model'), device='cpu', compute_type='int8',
                    inter_threads=1, intra_threads=cpu_threads())
                _runtimes[self.key] = tokenizer, translator
        finally:
            _runtime_lock.release()

    def translate(self, text, target_lang=None, checkpoint=lambda: None):
        if target_lang is not None and target_lang != self.target_lang:
            raise TranslationError('Target language does not match the selected direction')
        text = text.strip()
        checkpoint()
        if not text:
            return ''
        if text in self.cache:
            return self.cache[text]
        self.prepare(checkpoint)
        while not _runtime_lock.acquire(timeout=.1):
            checkpoint()
        try:
            tokenizer, translator = _runtimes[self.key]
            tokens = tokenizer.encode(text, out_type=str)
            pieces = []
            # Bound each inference call to improve cancellation and prevent input truncation.
            for start in range(0, len(tokens), 160):
                checkpoint()
                result = translator.translate_batch([tokens[start:start + 160]], beam_size=4,
                    replace_unknowns=True, max_input_length=0, max_decoding_length=512, length_penalty=.2)[0]
                checkpoint()
                output = result.hypotheses[0]
                if not output or len(output) >= 512:
                    raise TranslationError('Local model returned empty or truncated translation')
                pieces.append(tokenizer.decode(output).strip())
        finally:
            _runtime_lock.release()
        value = ' '.join(pieces)
        # Bound duplicate-cue caching on long videos.
        if len(self.cache) >= 256:
            self.cache.pop(next(iter(self.cache)))
        self.cache[text] = value
        return value


def release_translation_models():
    """No render keeps idle translation weights resident."""
    import gc
    with _runtime_lock:
        while _runtimes:
            _, (tokenizer, model) = _runtimes.popitem()
            model.unload_model()
            del model, tokenizer
    gc.collect()


class TranslatorProvider:
    def __init__(self, source_lang='en', target_lang='ar'):
        self.source_lang, self.target_lang = source_lang, target_lang
        self.cache = {}
        self.stages = [DirectTranslatorProvider(a, b) for a, b in translation_route(source_lang, target_lang)]

    def prepare(self, checkpoint=lambda: None, progress=lambda stage, fraction=None: None):
        # Install ahead of inference, but load just one runtime at a time for pivot translation.
        for stage in self.stages:
            ensure_model(checkpoint, progress, stage.source_lang, stage.target_lang)

    def translate(self, text, target_lang=None, checkpoint=lambda: None):
        if target_lang is not None and target_lang != self.target_lang:
            raise TranslationError('Target language does not match the selected direction')
        for stage in self.stages:
            text = stage.translate(text, checkpoint=checkpoint)
            # A pivot uses at most two runtimes. Retain them for this job;
            # unloading here reloaded both weights for every subtitle cue.
            # TranslationPipeline releases them before rendering and on failure.
        return text
