"""Regression tests for nonempty transcripts with missing vocal tails.

These are fake-ASR tests; they do NOT certify real singing transcription accuracy.
"""
from types import SimpleNamespace

import pytest

from translator import transcription


def cue(start, end, text, confidence=-0.15, speech=.05, repetition=1.1):
    return SimpleNamespace(start=start, end=end, text=text, avg_logprob=confidence,
                           no_speech_prob=speech, compression_ratio=repetition)


class FakeModel:
    def __init__(self, primary, retry, duration=247.574):
        self.primary, self.retry, self.duration = primary, retry, duration
        self.calls = []

    def transcribe(self, path, **kwargs):
        self.calls.append(kwargs)
        items = self.primary if kwargs.get('vad_filter') else self.retry
        return iter(items), SimpleNamespace(duration=self.duration)


@pytest.fixture
def install_fake(monkeypatch):
    def install(primary, retry, duration=247.574):
        model = FakeModel(primary, retry, duration)
        monkeypatch.setattr(transcription, '_model', model)
        monkeypatch.setattr(transcription, '_model_key', ('base.en', 'cpu'))
        return model
    yield install
    transcription._model = None
    transcription._model_key = None


def test_missing_tail_retried_without_vad_and_added_in_order(install_fake):
    model = install_fake([cue(21, 24, 'first'), cue(83, 84, 'second')],
                         [cue(21, 24, 'first'), cue(83, 84, 'second'),
                          cue(155, 158, 'recovered vocal')])
    results, info = transcription.Transcriber(model_size='base.en').transcribe('fake.wav')
    assert [r.text for r in results] == ['first', 'second', 'recovered vocal']
    assert [c['vad_filter'] for c in model.calls] == [True, False]
    assert info.duration == 247.574


def test_good_coverage_skips_extra_pass(install_fake):
    model = install_fake([cue(1, 5, 'start'), cue(243, 245, 'end')],
                         [cue(246, 247, 'unused')])
    results, _ = transcription.Transcriber(model_size='base.en').transcribe('fake.wav')
    assert len(results) == 2
    assert [c['vad_filter'] for c in model.calls] == [True]


def test_no_vad_music_hallucinations_are_not_added(install_fake):
    model = install_fake([cue(83, 84, 'original')],
                         [cue(145, 149, 'noise', confidence=-.85),
                          cue(155, 158, 'not speech', speech=.8),
                          cue(165, 168, 'repeated', repetition=2.8),
                          cue(170, 172, 'trusted')])
    results, _ = transcription.Transcriber(model_size='base.en').transcribe('fake.wav')
    assert [r.text for r in results] == ['original', 'trusted']


def test_no_vad_duplicate_or_overlap_is_rejected(install_fake):
    model = install_fake([cue(80, 84, 'original')],
                         [cue(81, 82, 'duplicate'), cue(84.1, 87, 'overlap'),
                          cue(90, 92, 'valid'), cue(91, 94, 'overlapping retry')])
    results, _ = transcription.Transcriber(model_size='base.en').transcribe('fake.wav')
    assert [r.text for r in results] == ['original', 'valid']


def test_short_missing_tail_does_not_force_second_pass(install_fake):
    model = install_fake([cue(80, 84, 'near-end')], [cue(85, 86, 'not used')], duration=90)
    results, _ = transcription.Transcriber(model_size='base.en').transcribe('fake.wav')
    assert len(results) == 1
    assert len(model.calls) == 1
