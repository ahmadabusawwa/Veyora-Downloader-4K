import math
from pathlib import Path


def format_timestamp(seconds):
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError('Invalid subtitle timestamp')
    total = round(seconds * 1000)
    hours, rest = divmod(total, 3600000)
    minutes, rest = divmod(rest, 60000)
    secs, millis = divmod(rest, 1000)
    return f'{hours:02}:{minutes:02}:{secs:02},{millis:03}'


def generate_srt(segments, output_path):
    with open(output_path, 'w', encoding='utf-8') as stream:
        for i, segment in enumerate(segments, 1):
            if segment.end < segment.start:
                raise ValueError('Subtitle ends before it starts')
            text = str(segment.text).replace('\r', '').replace('\n\n', '\n').strip()
            stream.write(f'{i}\n{format_timestamp(segment.start)} --> {format_timestamp(segment.end)}\n{text}\n\n')


def parse_srt(path):
    """Parse UTF-8 SRT while rejecting malformed or reversed time ranges."""
    import re
    from types import SimpleNamespace
    text = Path(path).read_text(encoding='utf-8-sig').replace('\r\n', '\n')
    segments = []
    def seconds(value):
        h, m, rest = value.split(':')
        sec, ms = rest.replace('.', ',').split(',')
        if int(m) > 59 or int(sec) > 59:raise ValueError('Invalid SRT timestamp')
        return int(h)*3600 + int(m)*60 + int(sec) + int(ms)/1000
    for block in re.split(r'\n\s*\n', text.strip()):
        lines = block.splitlines()
        if lines and lines[0].strip().isdigit():lines.pop(0)
        if not lines:continue
        match = re.fullmatch(r'(\d{2,}:\d{2}:\d{2}[,.]\d{3}) --> (\d{2,}:\d{2}:\d{2}[,.]\d{3})', lines[0].strip())
        if not match:raise ValueError('Invalid SRT cue')
        start,end = map(seconds,match.groups())
        if end < start:raise ValueError('Reversed SRT cue')
        segments.append(SimpleNamespace(start=start,end=end,text='\n'.join(lines[1:])))
    if not segments:raise ValueError('SRT contains no cues')
    return segments
