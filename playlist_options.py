"""Playlist settings are explicit and independent of hidden Dashboard defaults."""
import copy

QUALITIES={'best':'Best Available','2160':'2160p (4K)','1080':'1080p (Full HD)','720':'720p (HD)','480':'480p'}


def playlist_settings(base,quality='best',container='MP4',subtitles=False,source='auto',target='ar',mode='separate'):
    if quality not in QUALITIES or container not in ('MP4','MKV'):
        raise ValueError('Invalid playlist quality or container')
    if source not in ('auto','ar','en','tr','ko') or target not in ('ar','en','tr','ko') or mode not in ('separate','embed','burn'):
        raise ValueError('Invalid playlist subtitle options')
    result=copy.deepcopy(base)
    result.update(quality=QUALITIES[quality],format=container,download_subs=bool(subtitles),extract_audio=False,
                  subtitle_mode=mode,sub_lang=('detect-'+target if source=='auto' else 'auto-'+source+'-'+target),
                  force_container=True,strict_quality=True,clip_enabled=False,auto_split_clips=False)
    if source==target:result['sub_lang']='transcribe-'+source
    if source=='en' and target=='ar':result['sub_lang']='auto-ar'
    if source=='ar' and target=='en':result['sub_lang']='auto-en'
    return result
