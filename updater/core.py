import base64
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
from packaging.version import Version, InvalidVersion

REPOSITORY = 'ahmadabusawwa/Veyora-Downloader-4K'
API = f'https://api.github.com/repos/{REPOSITORY}/releases'
MAX_INSTALLER = 2 * 1024**3
# Provision an owner-controlled OFFLINE public key before enabling production updates.
TRUSTED_KEYS = {}

class UpdateError(Exception):
    pass

def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d+\.\d+\.\d+(?:(?:a|b|rc)\d+|-(?:alpha|beta|rc)[.-]?\d+)?', value):
        raise UpdateError('Invalid release version')
    try:
        return Version(value.removeprefix('v'))
    except InvalidVersion as exc:
        raise UpdateError('Invalid release version') from exc

def trusted_url(url, api=False):
    p = urlsplit(url)
    if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443) or p.fragment:
        raise UpdateError('Untrusted update URL')
    if api:
        valid = p.netloc == 'api.github.com' and p.path.startswith(f'/repos/{REPOSITORY}/releases')
    else:
        valid = (p.netloc == 'github.com' and p.path.startswith(f'/{REPOSITORY}/releases/download/')) or p.netloc == 'release-assets.githubusercontent.com'
    if not valid:
        raise UpdateError('Update host/path is not allowed')
    return url

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        trusted_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def open_url(url, api=False):
    trusted_url(url, api)
    request = urllib.request.Request(url, headers={'User-Agent':'Veyora-Pro-Updater/2.0', 'Accept':'application/vnd.github+json' if api else 'application/octet-stream'})
    return urllib.request.build_opener(SafeRedirect()).open(request, timeout=30)

def read_bounded(url, limit, api=False):
    with open_url(url, api) as response:
        value = response.read(limit + 1)
    if len(value) > limit:
        raise UpdateError('Update metadata exceeds size limit')
    return value

def verify_manifest(raw, signature, keys, expected_version, now=None):
    if len(raw) > 65536 or len(signature) > 4096:
        raise UpdateError('Oversized signed metadata')
    try:
        envelope = json.loads(signature)
        key = keys[envelope['key_id']]
        Ed25519PublicKey.from_public_bytes(base64.b64decode(key, validate=True)).verify(base64.b64decode(envelope['signature'], validate=True), raw)
        m = json.loads(raw)
        if m['schema'] != 1 or m['repository'] != REPOSITORY or m['platform'] != 'windows-x64':
            raise ValueError('Wrong manifest target')
        if version(m['version']) != version(expected_version):
            raise ValueError('Release/manifest version mismatch')
        if not isinstance(m['expires'], int) or m['expires'] < (time.time() if now is None else now):
            raise ValueError('Expired manifest')
        if not isinstance(m['size'], int) or not 0 < m['size'] <= MAX_INSTALLER:
            raise ValueError('Invalid installer size')
        if not re.fullmatch(r'[a-f0-9]{64}', m['sha256']):
            raise ValueError('Invalid digest')
        expected = f"Veyora-Pro-Setup-{str(version(m['version']))}.exe"
        if m['filename'] != expected:
            raise ValueError('Invalid installer name')
        trusted_url(m['url'])
        if not urlsplit(m['url']).path.startswith(f'/{REPOSITORY}/releases/download/{expected_version}/') or not m['url'].endswith('/' + expected):
            raise ValueError('Installer must belong to the selected release')
        return m
    except (KeyError, ValueError, TypeError, InvalidSignature) as exc:
        raise UpdateError('Update signature/manifest could not be verified') from exc

def verify_file(path, manifest):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size != manifest['size']:
        raise UpdateError('Installer size mismatch')
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):
            h.update(chunk)
    if h.hexdigest() != manifest['sha256']:
        raise UpdateError('Installer hash mismatch')

class UpdateClient:
    def __init__(self, current, directory, keys=None):
        self.current = version(current)
        self.directory = Path(directory)
        self.keys = TRUSTED_KEYS if keys is None else keys

    def check(self, prereleases=False):
        releases = json.loads(read_bounded(API + '?per_page=100', 2*1024*1024, api=True))
        candidates = []
        for release in releases:
            if release.get('draft') or (release.get('prerelease') and not prereleases):
                continue
            try:
                v = version(release.get('tag_name'))
            except UpdateError:
                continue
            if v > self.current and (prereleases or not v.is_prerelease):
                candidates.append((v, release))
        if not candidates:
            return None
        release = max(candidates, key=lambda x:x[0])[1]
        assets = {x['name']:x['browser_download_url'] for x in release.get('assets', [])}
        try:
            raw = read_bounded(assets['update-manifest.json'], 65536)
            sig = read_bounded(assets['update-manifest.sig'], 4096)
        except KeyError as exc:
            raise UpdateError('Release has no signed update metadata; installation blocked') from exc
        manifest = verify_manifest(raw, sig, self.keys, release['tag_name'])
        return dict(manifest=manifest, raw=raw, signature=sig, tag=release['tag_name'], notes=str(release.get('body') or '')[:20000])

    def download(self, release, progress=lambda value:None, cancelled=lambda:False):
        m = verify_manifest(release['raw'], release['signature'], self.keys, release['tag'])
        self.directory.mkdir(parents=True, exist_ok=True)
        # Unique private staging folder prevents collisions with earlier update attempts.
        stage = Path(tempfile.mkdtemp(prefix='verified-update-', dir=self.directory))
        os.chmod(stage, 0o700)
        part = stage / 'installer.part'
        try:
            total = 0
            with open_url(m['url']) as response, part.open('xb') as out:
                while True:
                    if cancelled():
                        raise UpdateError('Update download cancelled')
                    chunk = response.read(256*1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > m['size']:
                        raise UpdateError('Installer exceeds signed size')
                    out.write(chunk)
                    progress(total / m['size'])
            verify_file(part, m)
            target = stage / m['filename']
            os.replace(part, target)
            (stage/'update-manifest.json').write_bytes(release['raw'])
            (stage/'update-manifest.sig').write_bytes(release['signature'])
            return target
        except Exception:
            part.unlink(missing_ok=True)
            raise
