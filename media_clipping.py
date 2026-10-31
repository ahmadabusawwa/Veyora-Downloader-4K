"""Validated local clipping after download; never misrepresents partial retrieval."""
import math
from pathlib import Path
import tempfile
import uuid
from translator.video_renderer import get_ffprobe_info,run_ffmpeg
from translator.subtitle_generator import parse_srt,generate_srt
from types import SimpleNamespace


def time_seconds(value):
    fields=str(value).strip().split(':')
    if not 1<=len(fields)<=3:raise ValueError('Invalid clip time; use HH:MM:SS')
    try:numbers=[float(v) for v in fields]
    except ValueError as exc:raise ValueError('Invalid clip time; use HH:MM:SS') from exc
    if any(not math.isfinite(v) or v<0 for v in numbers) or any(v>=60 for v in numbers[1:]):
        raise ValueError('Invalid clip time; use HH:MM:SS')
    return sum(v*60**i for i,v in enumerate(reversed(numbers)))


def clip_interval(start,end,duration=None):
    start,end=time_seconds(start),time_seconds(end)
    if end<=start:raise ValueError('Clip end must be later than start')
    if duration is not None and (start>=duration or end>duration+.05):
        raise ValueError('Clip interval exceeds the media duration')
    return start,end


def clip_subtitles(path,start,end,output):
    cues=[]
    for cue in parse_srt(path):
        left,right=max(cue.start,start),min(cue.end,end)
        if right>left:cues.append(SimpleNamespace(start=left-start,end=right-start,text=cue.text))
    if not cues:raise ValueError('No subtitles are available in the selected clip interval')
    generate_srt(cues,output)
    return Path(output)


def clip_media(media,output_dir,start,end,checkpoint=lambda:None,progress=None):
    media=Path(media);output_dir=Path(output_dir)
    info=get_ffprobe_info(media);duration=float(info.get('format',{}).get('duration',0))
    if not math.isfinite(duration) or duration<=0:raise ValueError('Media duration is unavailable for clipping')
    start,end=clip_interval(start,end,duration)
    if not any(s.get('codec_type')=='video' for s in info.get('streams',[])):
        raise ValueError('Video clipping requires a video stream')
    output_dir.mkdir(parents=True,exist_ok=True)
    suffix=media.suffix.lower() if media.suffix.lower() in ('.mp4','.mkv') else '.mp4'
    output=output_dir/(media.stem+'.clip.'+uuid.uuid4().hex[:12]+suffix)
    # Accurate output seeking, timestamps reset by FFmpeg; re-encode avoids
    # keyframe-dependent intervals and supports the downloader's input codecs.
    with tempfile.TemporaryDirectory(prefix='veyora-clip-',dir=output_dir) as folder:
        temporary=Path(folder)/('clip'+suffix)
        run_ffmpeg(['-i',media,'-ss',str(start),'-t',str(end-start),'-map','0:v:0','-map','0:a?',
            '-sn','-c:v','libx264','-threads','2','-preset','medium','-crf','20',
            '-c:a','aac','-movflags','+faststart',temporary],checkpoint,duration=end-start,progress=progress)
        check=get_ffprobe_info(temporary);actual=float(check.get('format',{}).get('duration',0))
        if not math.isfinite(actual) or abs(actual-(end-start))>.3 or not any(s.get('codec_type')=='video' for s in check.get('streams',[])):
            raise ValueError('Clipped video output validation failed')
        checkpoint();temporary.replace(output)
    return output


def split_long_video(media,output_dir,checkpoint=lambda:None,progress=lambda *a:None,seconds=600,subtitle=None,subtitle_mode='separate',language='ar'):
    """Keep the validated full export and add bounded, independently usable parts."""
    from translator.video_renderer import embed_subtitles
    duration=float(get_ffprobe_info(media)['format']['duration'])
    if not math.isfinite(duration) or duration<=0:raise ValueError('Invalid media duration')
    if not math.isfinite(seconds) or seconds<=0:raise ValueError('Invalid split duration')
    if duration<=seconds:return []
    parts=[];start=0
    while start<duration-.01:
        checkpoint();end=min(duration,start+seconds)
        progress('Splitting completed video into parts',start/duration)
        part=clip_media(media,output_dir,start,end,checkpoint)
        if subtitle:
            # An instrumental/silent part legitimately may have no captions.
            cues=parse_srt(subtitle)
            if any(min(s.end,end)>max(s.start,start) for s in cues):
                shifted=clip_subtitles(subtitle,start,end,part.with_suffix('.srt'))
                if subtitle_mode in ('embed','both'):
                    embedded=part.with_name(part.stem+'.subtitled'+part.suffix)
                    embed_subtitles(part,shifted,embedded,checkpoint,subtitle_lang=language)
                    parts.append(str(embedded));start=end;continue
        parts.append(str(part));start=end
    return parts
