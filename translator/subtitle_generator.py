import math
import os
import tempfile
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
    destination = Path(output_path)
    prepared=[]
    previous_start=-1
    for segment in segments:
        if not isinstance(segment.text,str):raise ValueError('Subtitle text must be a string')
        text='\n'.join(line for line in segment.text.replace('\r','').splitlines() if line.strip()).strip()
        start,end=format_timestamp(segment.start),format_timestamp(segment.end)
        if not text:raise ValueError('Subtitle contains an empty cue')
        if round(segment.end*1000)<=round(segment.start*1000):raise ValueError('Subtitle has no positive display duration')
        if segment.start<previous_start:raise ValueError('Subtitle timestamps are not chronological')
        previous_start=segment.start
        prepared.append((start,end,text))
    if not prepared:raise ValueError('No subtitle cues were produced')
    fd, temporary = tempfile.mkstemp(prefix='subtitle-', suffix='.partial', dir=destination.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            for i,(start,end,text) in enumerate(prepared,1):
                stream.write(f'{i}\n{start} --> {end}\n{text}\n\n')
        # Validate the actual serialized file before the atomic publish. This
        # checks every expected cue, not whether speech must fill the video.
        actual=parse_srt(temporary)
        if len(actual)!=len(prepared) or any((format_timestamp(a.start),format_timestamp(a.end),a.text)!=expected for a,expected in zip(actual,prepared)):
            raise ValueError('Subtitle serialization is incomplete')
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)



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
        if lines and lines[0].strip().isdigit():
            if int(lines.pop(0).strip())!=len(segments)+1:raise ValueError('Invalid SRT cue numbering')
        if not lines:continue
        match = re.fullmatch(r'(\d{2,}:\d{2}:\d{2}[,.]\d{3}) --> (\d{2,}:\d{2}:\d{2}[,.]\d{3})', lines[0].strip())
        if not match:raise ValueError('Invalid SRT cue')
        start,end = map(seconds,match.groups())
        if end <= start:raise ValueError('SRT cue must have positive duration')
        if segments and start<segments[-1].start:raise ValueError('SRT timestamps are not chronological')
        content='\n'.join(lines[1:]).strip()
        if not content:raise ValueError('SRT contains an empty cue')
        segments.append(SimpleNamespace(start=start,end=end,text=content))
    if not segments:raise ValueError('SRT contains no cues')
    return segments
