"""Join split phrases before translation, preserving their full time interval.

No translated text is heuristically split back into old timestamps. Bounded
merged cues keep output timing truthful across different word orders.
"""
import re
from types import SimpleNamespace


def sentence_groups(segments, max_seconds=12, max_chars=360):
    pending = []
    def joined():
        return SimpleNamespace(start=pending[0].start,end=pending[-1].end,
            text=' '.join(s.text.strip() for s in pending).strip())
    for segment in segments:
        if pending and (segment.end-pending[0].start > max_seconds or
                        sum(len(s.text)+1 for s in pending)+len(segment.text)>max_chars or
                        segment.start-pending[-1].end > 1.5):
            yield joined();pending=[]
        pending.append(segment)
        if re.search(r'[.!?؟。！？][\"\'”’]?\s*$',segment.text):
            yield joined();pending=[]
    if pending: yield joined()
