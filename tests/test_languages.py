import pytest
from translator.offline_model import translation_route, model_entry
from translator.transcription import Transcriber
from translator.pipeline import _cache_key
from main import TRANSLATION_DIRECTIONS, SUBTITLE_CHOICES

@pytest.mark.parametrize('source',['ar','en','tr','ko'])
@pytest.mark.parametrize('target',['ar','en','tr','ko'])
def test_routes(source,target):
    if source == target:return
    route=translation_route(source,target)
    assert route[0][0]==source and route[-1][1]==target
    for a,b in route:assert model_entry(a,b)['sha256']
    assert (source,target) in TRANSLATION_DIRECTIONS.values()

@pytest.mark.parametrize('language',['tr','ko'])
def test_multilingual_speech_and_cache(language,tmp_path):
    t=Transcriber(language=language)
    assert t.model_size=='base' and t.language==language
    media=tmp_path/'video';media.write_bytes(b'video')
    assert _cache_key(media,lambda:None,language)!=_cache_key(media,lambda:None,'ar')
    assert language in SUBTITLE_CHOICES.values()

def test_auto_detect_uses_multilingual_model():
    t=Transcriber(language='auto')
    assert t.model_size=='base'
    assert ('auto','ar') in TRANSLATION_DIRECTIONS.values()


def test_srt_parser_roundtrip_and_bad_time(tmp_path):
    from translator.subtitle_generator import parse_srt, generate_srt
    from types import SimpleNamespace
    p=tmp_path/'input.srt'
    generate_srt([SimpleNamespace(start=1.25,end=2.5,text='مرحبا\n안녕하세요')],p)
    value=parse_srt(p)
    assert value[0].start==1.25 and value[0].text=='مرحبا\n안녕하세요'
    p.write_text('1\n00:00:03,000 --> 00:00:01,000\nWrong\n',encoding='utf8')
    with pytest.raises(ValueError):parse_srt(p)
