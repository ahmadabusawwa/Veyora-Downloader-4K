"""Conservative, observable original/candidate comparison, never source replacement.

ASR confidence is a heuristic, not a reference-quality score. No VAD settings or
model sizes change here. The unchanged transcript wins inconclusive comparisons.
"""
from collections import Counter
import math
import re
import wave
import array
import sys


def audio_activity(path):
    """One-second PCM energy bins; audible audio is not proof of speech."""
    with wave.open(str(path),'rb') as stream:
        if stream.getsampwidth()!=2 or stream.getnchannels()!=1:return None
        rate=stream.getframerate();active=[];index=0
        while True:
            raw=stream.readframes(rate)
            if not raw:break
            samples=array.array('h',raw)
            if sys.byteorder!='little':samples.byteswap()
            rms=math.sqrt(sum(x*x for x in samples)/max(1,len(samples)))/32768
            if rms>.005:active.append(index)
            index+=1
        return dict(duration=stream.getnframes()/rate,active_seconds=active)


def needs_candidate(segments,activity):
    if activity is None:return False
    last=max((s.end for s in segments),default=0)
    tail=sum(t>last+2 for t in activity['active_seconds'])
    weak=any(getattr(s,'avg_logprob',0)<-.7 for s in segments)
    return tail>=8 or weak


def _words(segments):
    return re.findall(r'\w+',' '.join(s.text for s in segments).casefold())


def prefer_candidate(original,candidate):
    if not candidate:return False
    if any(not s.text.strip() or getattr(s,'avg_logprob',-99)<-.6 or
           getattr(s,'no_speech_prob',1)>.3 or getattr(s,'compression_ratio',99)>2.2 for s in candidate):return False
    old,new=Counter(_words(original)),Counter(_words(candidate))
    if not new:return False
    # Do not replace recognizable words with a different confident hallucination.
    if old and sum((old&new).values())/sum(old.values())<.95:return False
    # Repetition is especially hazardous in musical tails.
    if any(count>max(3,old[word]*2) for word,count in new.items()):return False
    if not original:return True
    if min(s.start for s in candidate)>min(s.start for s in original)+.5:return False
    if max(s.end for s in candidate)<max(s.end for s in original)-.5:return False
    score=lambda cues:sum(getattr(s,'avg_logprob',-99)*max(.01,s.end-s.start) for s in cues)/sum(max(.01,s.end-s.start) for s in cues)
    return score(candidate)>score(original)+.15
