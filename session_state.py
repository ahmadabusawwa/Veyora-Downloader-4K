"""Privacy-aware public-link drafts; navigation never initiates network work."""
from urllib.parse import urlsplit, parse_qsl


def public_draft(url):
    try:
        parts = urlsplit(url.strip())
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
            return ''
        # Signed media links and arbitrary query secrets must not survive a restart.
        allowed = {'v', 'list', 'index', 't', 'start', 'feature', 'si'}
        if parts.fragment or any(key.lower() not in allowed for key, _ in parse_qsl(parts.query)):
            return ''
        if parts.port not in (None, 80, 443):
            return ''
        return url.strip()
    except ValueError:
        return ''
