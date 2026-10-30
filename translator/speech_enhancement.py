"""Optional stereo dialogue processing; never modifies final video's audio.

This is center-channel enhancement, not neural source separation. Mono and
centered music cannot reliably be separated this way; users can leave it off.
"""
from .video_renderer import get_ffprobe_info, run_ffmpeg


def enhance_speech(media, output, checkpoint=lambda:None):
    audio = next((s for s in get_ffprobe_info(media)['streams'] if s.get('codec_type') == 'audio'), None)
    if audio is None:
        raise ValueError('Media has no audio track')
    channels = audio.get('channels', 1)
    filters = 'highpass=f=100,lowpass=f=7600,afftdn=nf=-25'
    if channels >= 2:
        # dialoguenhance derives a dialogue center channel from a stereo mix.
        filters = 'aformat=channel_layouts=stereo,dialoguenhance=enhance=2:voice=8,pan=mono|c0=c2,' + filters
    run_ffmpeg(['-i',media,'-vn','-af',filters,'-acodec','pcm_s16le','-ar','16000','-ac','1',output],checkpoint)
