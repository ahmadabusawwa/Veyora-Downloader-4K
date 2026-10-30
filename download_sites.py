"""Site routing and short-link support on top of yt-dlp's native extractors.

A recognized host/extractor is a routing hint, not a guarantee of a live download.
"""
import re
from privacy import redact, QuietLogger
from urllib.parse import urlsplit, urlunsplit, parse_qs
import yt_dlp
from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.extractor.pinterest import PinterestIE, PinterestCollectionIE
from yt_dlp.utils import ExtractorError

SUPPORTED_PLATFORMS = {
    'youtube.com': 'YouTube', 'youtu.be': 'YouTube',
    'tiktok.com': 'TikTok', 'instagram.com': 'Instagram',
    'facebook.com': 'Facebook', 'fb.watch': 'Facebook',
    'twitter.com': 'Twitter/X', 'x.com': 'Twitter/X', 't.co': 'Twitter/X',
    'reddit.com': 'Reddit', 'redd.it': 'Reddit', 'v.redd.it': 'Reddit',
    'vimeo.com': 'Vimeo', 'dailymotion.com': 'Dailymotion', 'dai.ly': 'Dailymotion',
    'twitch.tv': 'Twitch', 'clips.twitch.tv': 'Twitch', 'soundcloud.com': 'SoundCloud',
    'pin.it': 'Pinterest', 'bilibili.com': 'Bilibili', 'b23.tv': 'Bilibili',
    'vk.com': 'VK', 'vkvideo.ru': 'VK', 'ok.ru': 'OK.ru',
    'rumble.com': 'Rumble', 'odysee.com': 'Odysee', 'bitchute.com': 'BitChute',
    'streamable.com': 'Streamable', 'imgur.com': 'Imgur', 'tumblr.com': 'Tumblr',
    'bandcamp.com': 'Bandcamp', 'mixcloud.com': 'Mixcloud', 'nicovideo.jp': 'NicoNico',
    'weibo.com': 'Weibo', 'linkedin.com': 'LinkedIn', 'snapchat.com': 'Snapchat Spotlight',
}
# These regional hosts are supported by the installed native Pinterest extractor.
PINTEREST_SUFFIXES = ('com fr de ch jp cl ca it co.uk nz ru com.au at pt co.kr es com.mx '
                     'dk ph th com.uy co nl info kr ie vn com.vn ec mx in pe co.at hu '
                     'co.in co.nz id com.ec com.py tw be uk com.bo com.pe').split()
SUPPORTED_PLATFORMS.update({'pinterest.' + suffix: 'Pinterest' for suffix in PINTEREST_SUFFIXES})
POPULAR_SITES = tuple(sorted(set(SUPPORTED_PLATFORMS.values()), key=str.lower))


def normalize_url(value):
    value = str(value or '').strip()
    if value.startswith('<') and value.endswith('>'):
        value = value[1:-1].strip()
    if not value or len(value) > 8192 or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError('Paste one complete video URL, without spaces or multiple lines')
    if '://' not in value and re.match(r'^(?:[\w-]+\.)+[\w-]+(?::\d+)?(?:/|$)', value):
        value = 'https://' + value
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Only HTTP(S) video links are supported')
    if parsed.username is not None or parsed.password is not None:
        raise ValueError('Do not put account credentials in the URL; use a cookies file in Settings')
    try:
        port = parsed.port  # validates malformed/out-of-range ports
        host = parsed.hostname.encode('idna').decode('ascii').lower()
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Invalid video URL host or port') from exc
    if ':' in host:
        host = '[' + host + ']'
    netloc = host + (':' + str(port) if port is not None else '')
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or '/', parsed.query, parsed.fragment))


def detect_platform(value):
    try:
        host = urlsplit(normalize_url(value)).hostname
        for domain, name in SUPPORTED_PLATFORMS.items():
            if host == domain or host.endswith('.' + domain):
                return name
        return 'Other website / direct media'
    except ValueError:
        return 'Unknown'


def is_valid_url(value):
    try:
        normalize_url(value)
        return True
    except (ValueError, TypeError):
        return False


class PinterestShortLinkIE(InfoExtractor):
    IE_NAME = 'Veyora:PinterestShortLink'
    _VALID_URL = r'https?://(?:www\.)?pin\.it/(?P<id>[A-Za-z0-9_-]+)(?:[/?#].*)?$'

    def _real_extract(self, url):
        link_id = self._match_id(url)
        response = self._request_webpage(url, link_id, note='Resolving Pinterest short link')
        target = normalize_url(response.url)
        # Use the downloader's own session, timeout, cookies, proxy and redirect handling.
        # Do not interpret page HTML as executable code or turn unrelated redirect targets into Pinterest.
        if PinterestIE.suitable(target):
            return self.url_result(target, ie=PinterestIE.ie_key())
        if PinterestCollectionIE.suitable(target) and detect_platform(target) == 'Pinterest':
            return self.url_result(target, ie=PinterestCollectionIE.ie_key())
        raise ExtractorError('Pinterest short link did not resolve to a public pin/board. Paste the full pinterest.com/pin/ URL.', expected=True)


def create_downloader(options):
    options = dict(options)
    options.setdefault("logger", QuietLogger())
    downloader = yt_dlp.YoutubeDL(options, auto_init=False)
    downloader.add_info_extractor(PinterestShortLinkIE())
    downloader.add_default_info_extractors()  # preserve native and generic site support
    return downloader


def metadata_options(url, cookies_file=''):
    options = dict(quiet=True, no_warnings=True, skip_download=True, noplaylist=True,
                   extract_flat='in_playlist', socket_timeout=20, retries=2, extractor_retries=2,
                   nocheckcertificate=False)
    if cookies_file:
        from pathlib import Path
        if Path(cookies_file).is_file():
            options['cookiefile'] = cookies_file
    return options


def entry_page_url(entry, platform):
    # A generic HTML page can contain several videos with the same webpage_url.
    # Preserve each actual media entry instead of enqueueing that page repeatedly.
    if platform == 'Other website / direct media':
        candidates = [entry.get('url')] + [f.get('url') for f in reversed(entry.get('formats') or [])]
        for candidate in candidates:
            if candidate and is_valid_url(candidate):
                return normalize_url(candidate)
    for key in ('webpage_url', 'original_url', 'url'):
        value = entry.get(key)
        if value and is_valid_url(value):
            return normalize_url(value)
    video_id = str(entry.get('id') or entry.get('url') or '')
    if platform == 'Pinterest' and video_id.isdigit():
        return 'https://www.pinterest.com/pin/' + video_id + '/'
    if platform == 'YouTube' and re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        return 'https://www.youtube.com/watch?v=' + video_id
    return ''


def friendly_download_error(url, error):
    message = redact(error)
    lowered = message.lower()
    site = detect_platform(url)
    if 'certificate_verify_failed' in lowered or 'certificate verify failed' in lowered:
        return f'{site}: TLS certificate verification failed. Check trusted certificates/network configuration; certificate checks remain enabled.'
    if '429' in lowered or 'too many requests' in lowered or 'rate limit' in lowered:
        return f'{site}: the source is rate-limiting requests. Wait and retry later.'
    if any(term in lowered for term in ('drm', 'digital rights management')):
        return f'{site}: this media uses DRM and cannot be downloaded by this app.'
    if any(term in lowered for term in ('login required', 'log in', 'sign in', 'login', 'cookies', 'private video', 'private content', 'authentication')):
        return f'{site}: this content may require an account with access. Add your own cookies.txt in Settings. Access restrictions still apply.'
    if site == 'Pinterest' and any(term in lowered for term in ('no video', 'no formats', 'no media')):
        return 'Pinterest: video extraction returned no formats. This does not prove the pin is an image. Original error: ' + message
    if 'unsupported url' in lowered:
        return f'{site}: no extractor recognized this link. Try the full video-page URL or a direct media URL.'
    if '403' in lowered or 'forbidden' in lowered:
        return f'{site}: the source denied the request (403). Account, region or source-side restrictions may apply.'
    if any(term in lowered for term in ('timed out', 'timeout', 'name resolution', 'connection error')):
        return f'{site}: network request failed or timed out. Check your connection and try later.'
    return message
