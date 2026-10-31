"""Conservative automatic policy. Unproven separation is never forced on all media."""

def speech_mode(value=None):
    if value is True or value=='on':return 'on'
    if value is False or value=='off':return 'off'
    if value in (None,'auto'):return 'auto'
    raise ValueError('Invalid speech processing policy')


def should_enhance(value):
    # Auto starts with the original; pipeline compares an enhanced candidate
    # only for suspicious coverage/confidence. Explicit on is a test override.
    return speech_mode(value)=='on'


def configured_translation_options(settings):
    """Both entry points use automatic policy, independent of legacy UI flags.

    Legacy choices remain stored as user data for rollback; they no longer disable
    the integrated engine. Explicit pipeline arguments remain test/CLI overrides.
    """
    return dict(enhance_speech='auto',contextual_translation=None)


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
