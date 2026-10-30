"""Conversion options never invoke a speech or translation engine."""

def conversion_arguments(mode, options):
    if mode == 'MP3':
        if options.get('audio_bitrate','192k') not in ('128k','192k','256k','320k'):
            raise ValueError('Unsupported audio bitrate')
        return ['-vn', '-c:a', 'libmp3lame', '-b:a', options.get('audio_bitrate', '192k')]
    if mode == 'WAV':
        return ['-vn', '-c:a', 'pcm_s16le']
    if mode not in ('MP4', 'MKV'):
        raise ValueError('Unsupported conversion format')
    codec = options.get('codec', 'h264')
    if codec not in ('h264', 'h265'):
        raise ValueError('Unsupported video codec')
    result = ['-threads','2','-c:v', 'libx264' if codec == 'h264' else 'libx265', '-c:a', 'aac']
    resolution = options.get('resolution', 'original')
    if resolution != 'original':
        if resolution not in ('480', '720', '1080', '2160'):
            raise ValueError('Unsupported resolution')
        result += ['-vf', f'scale=-2:{resolution}']
    quality=options.get('quality','auto')
    if quality not in ('auto','high','medium','custom'):
        raise ValueError('Unsupported output quality')
    if quality!='custom' and options.get('bitrate','auto')=='auto':
        result += ['-crf',str({'auto':23,'high':18,'medium':26}[quality]),'-preset','fast']
    bitrate = options.get('bitrate', 'auto')
    if bitrate != 'auto':
        if bitrate not in ('1000k', '2500k', '5000k', '10000k'):
            raise ValueError('Unsupported bitrate')
        result += ['-b:v', bitrate]
    return result
