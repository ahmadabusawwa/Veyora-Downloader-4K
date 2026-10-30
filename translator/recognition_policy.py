"""Conservative automatic policy. Unproven separation is never forced on all media."""

def speech_mode(value=None):
    if value is True or value=='on':return 'on'
    if value is False or value=='off':return 'off'
    if value in (None,'auto'):return 'auto'
    raise ValueError('Invalid speech processing policy')


def should_enhance(value):
    # The fixed 2.0.3 comparisons did not show a repeatable gain on music.
    # Auto retains original audio until a rule passes the fixed benchmark.
    # Manual on remains available for stereo-centered dialogue.
    return speech_mode(value)=='on'


def automatic_context(segments):
    import re
    from .context_segments import sentence_groups
    pending=[]
    pronoun=re.compile(r"^(?:(?:but|and|so)\s+)?(?:they|them|he|she|it|this|that|هو|هي|هم|هن|لكنها|لكنهم|إنها|إنهم|onlar|o|그|그녀|그것)\b",re.I)
    for segment in segments:
        if pending:
            finished=bool(re.search(r'[.!?؟。！？][\"\'”’]?\s*$',pending[-1].text))
            if finished and not pronoun.search(segment.text.strip()):
                yield from sentence_groups(pending);pending=[]
        pending.append(segment)
    if pending:yield from sentence_groups(pending)
