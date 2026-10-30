import functools
import http.server
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import main
from download_sites import (normalize_url, detect_platform, is_valid_url, PinterestShortLinkIE,
    create_downloader, metadata_options, entry_page_url, friendly_download_error)
from yt_dlp.extractor import gen_extractor_classes
from yt_dlp.extractor.pinterest import PinterestIE
from yt_dlp.utils import ExtractorError


@pytest.mark.parametrize('url,normalized,platform',[
 ('pin.it/AbC123', 'https://pin.it/AbC123','Pinterest'),
 ('<https://www.pinterest.co.uk/pin/123/>','https://www.pinterest.co.uk/pin/123/','Pinterest'),
 ('https://m.youtube.com/watch?v=BaW_jenozKc','https://m.youtube.com/watch?v=BaW_jenozKc','YouTube'),
 ('https://vm.tiktok.com/a/','https://vm.tiktok.com/a/','TikTok'),
 ('https://fb.watch/test/','https://fb.watch/test/','Facebook'),
 ('https://dai.ly/x123','https://dai.ly/x123','Dailymotion'),
 ('https://x.com/user/status/123','https://x.com/user/status/123','Twitter/X'),
 ('https://b23.tv/abc','https://b23.tv/abc','Bilibili'),
])
def test_normalize_and_detect(url, normalized, platform):
    assert normalize_url(url) == normalized
    assert detect_platform(url) == platform


@pytest.mark.parametrize('url',['javascript:alert(1)','file:///tmp/video.mp4','https://user:pass@example.com/x',
                               'https://example.com:99999/x','https://a.com/x\nhttps://b.com/y','not a URL'])
def test_invalid_urls_rejected(url):
    assert not is_valid_url(url)


def test_host_detection_does_not_match_lookalike_domains():
    assert detect_platform('https://notpinterest.com/pin/1') != 'Pinterest'
    assert detect_platform('https://youtube.com.evil.example/video') != 'YouTube'
    assert detect_platform('https://anything.example/direct.mp4') == 'Other website / direct media'


def test_pinterest_short_link_routes_to_native_pin_extractor():
    extractor = PinterestShortLinkIE()
    extractor._request_webpage = Mock(return_value=SimpleNamespace(url='https://www.pinterest.com/pin/664281013778109217/'))
    info = extractor._real_extract('https://pin.it/Abc123')
    assert info['ie_key'] == 'Pinterest'
    assert info['url'].startswith('https://www.pinterest.com/pin/')


def test_pinterest_short_link_rejects_unrelated_redirect():
    extractor = PinterestShortLinkIE()
    extractor._request_webpage = Mock(return_value=SimpleNamespace(url='https://unrelated.example/login'))
    with pytest.raises(ExtractorError, match='did not resolve'):
        extractor._real_extract('https://pin.it/Abc123')


def test_factory_preserves_all_native_and_generic_extractors():
    with create_downloader({'quiet':True,'no_warnings':True}) as downloader:
        assert 'Veyora:PinterestShortLink' in [ie.IE_NAME for ie in downloader._ies.values()]
        assert 'Pinterest' in downloader._ies
        assert 'Generic' in downloader._ies
        assert 'Youtube' in downloader._ies


def test_metadata_no_false_tiktok_playlist_heuristic():
    options = metadata_options('https://www.tiktok.com/@example/video/123')
    assert options['noplaylist'] is True
    assert options['extract_flat'] == 'in_playlist'
    assert options['nocheckcertificate'] is False


def test_non_youtube_playlist_entry_urls_and_missing_audio_bitrate(monkeypatch):
    info = {'entries':[{'id':'12345678','title':'Pin','webpage_url':'https://www.pinterest.com/pin/12345678/'}]}
    fake = Mock()
    fake.__enter__ = Mock(return_value=fake)
    fake.__exit__ = Mock(return_value=False)
    fake.extract_info.return_value = info
    monkeypatch.setattr(main, 'create_downloader', lambda _: fake)
    result = main.DownloadEngine.fetch_metadata('https://www.pinterest.com/creator/board/')
    assert result['entries'][0]['url'] == 'https://www.pinterest.com/pin/12345678/'
    fake.extract_info.return_value = {'id':'a','title':'Audio','formats':[{'format_id':'audio','acodec':'aac','vcodec':'none','ext':'m4a','abr':None}]}
    result = main.DownloadEngine.fetch_metadata('https://example.com/a')
    assert result['audio_formats'][0]['abr'] == 0
    assert not entry_page_url({'id':'98765'},'Vimeo').startswith('https://www.youtube.com')


@pytest.mark.parametrize('url',[ # Routing checks against the real installed extractors, no live-site guarantee.
 'https://www.youtube.com/watch?v=BaW_jenozKc',
 'https://www.pinterest.com/pin/664281013778109217/',
 'https://www.tiktok.com/@example/video/7105032504014359846',
 'https://www.instagram.com/p/aye83DjauH/',
 'https://www.facebook.com/watch/?v=637842556329505',
 'https://x.com/example/status/1506713280000000000',
 'https://www.reddit.com/r/videos/comments/6rrwyj/example/',
 'https://vimeo.com/76979871',
 'https://www.dailymotion.com/video/x8abcde',
 'https://www.twitch.tv/videos/123456789',
 'https://soundcloud.com/artist/track',
 'https://www.bilibili.com/video/BV1xx411c7mD',
])
def test_popular_urls_have_non_generic_native_routes(url):
    matches=[ie for ie in gen_extractor_classes() if ie.ie_key()!='Generic' and ie.suitable(url)]
    assert matches, url


def test_errors_are_specific_without_claiming_access_bypass():
    assert 'rate-limiting' in friendly_download_error('https://pin.it/abc','HTTP 429 Too Many Requests')
    assert 'Original error' in friendly_download_error('https://pinterest.com/pin/123','No video formats found')
    assert 'DRM' in friendly_download_error('https://example.com','This video is DRM protected')
    assert 'cookies.txt' in friendly_download_error('https://instagram.com/p/abc','Login required')
    assert 'certificate checks remain enabled' in friendly_download_error('https://pinterest.com/pin/123','certificate verify failed')


def test_metadata_errors_visible_in_gui(monkeypatch):
    error = Mock()
    monkeypatch.setattr(main.messagebox, 'showerror', error)
    main.VeyoraApp.handle_metadata_result(SimpleNamespace(), 'https://pin.it/test', {'error':'Pinterest: test failure'})
    error.assert_called_once_with('Could not read this link','Pinterest: test failure')


def test_actual_download_via_short_link_and_native_pinterest_with_local_fixture(monkeypatch, tmp_path):
    from translator.video_renderer import run_ffmpeg
    media=tmp_path/'pin.mp4'
    run_ffmpeg(['-f','lavfi','-i','color=c=blue:s=320x240:d=1','-c:v','libx264','-threads','2',media])
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self,*args): pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        pin='https://www.pinterest.com/pin/664281013778109217/'
        monkeypatch.setattr(PinterestShortLinkIE,'_request_webpage',lambda *args,**kwargs:SimpleNamespace(url=pin))
        data={'id':'664281013778109217','title':'Local Pinterest fixture','domain':'uploaded by user',
              'videos':{'video_list':{'V_720P':{'url':f'http://127.0.0.1:{server.server_port}/pin.mp4','width':320,'height':240,'duration':1000}}}}
        monkeypatch.setattr(PinterestIE,'_call_api',lambda *args,**kwargs:{'data':data})
        target=tmp_path/'downloads'
        task={'id':'pinterest-local','url':'https://pin.it/Abc123','title':'Resolving...',
              'settings':{**main.DEFAULT_SETTINGS,'download_dir':str(target),'download_subs':False,'save_thumbnail':False}}
        outcomes=[]
        main.DownloadEngine.download_task(task,lambda *_:None,lambda *args:outcomes.append(args),threading.Event(),threading.Event(),str(target))
        assert outcomes[0][1],outcomes
        assert Path(task['downloaded_file']).read_bytes()==media.read_bytes()
    finally:
        server.shutdown();server.server_close()


def test_manifest_byte_ranges_not_overridden(tmp_path):
    from main import DownloadEngine
    opts, _ = DownloadEngine.build_ydl_opts({'id': 'range', 'url': 'https://pin.it/1qB80dshH', 'settings': {}}, lambda *args: None, tmp_path)
    assert 'http_chunk_size' not in opts
    assert opts['skip_unavailable_fragments'] is False


def test_image_word_does_not_mask_original_error():
    assert friendly_download_error('https://pin.it/abc', 'Unable to download image metadata: server error') == 'Unable to download image metadata: server error'
