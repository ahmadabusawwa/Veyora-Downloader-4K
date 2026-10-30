"""Bounded disk thumbnail cache; decoded images returned on a worker."""
import hashlib
import io
import os
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='thumbnail-cache')
_lock = threading.Lock()
_inflight = {}
MAX_BYTES = 32 * 1024 * 1024


def _load(url, root):
    from PIL import Image, ImageOps
    import requests
    from urllib.parse import urlsplit
    if urlsplit(url).scheme not in ('http', 'https'):
        raise ValueError('Unsupported thumbnail URL')
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / (hashlib.sha256(url.encode()).hexdigest() + '.jpg')
    with _lock:
        if path.exists():
            with Image.open(path) as img:
                result = img.copy()
            os.utime(path, None)
            return result
    with requests.get(url, stream=True, timeout=(5, 10)) as response:
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_content(32768):
            size += len(chunk)
            if size > 4 * 1024 * 1024:
                raise ValueError('Thumbnail is too large')
            chunks.append(chunk)
    with Image.open(io.BytesIO(b''.join(chunks))) as img:
        if img.width * img.height > 20_000_000:
            raise ValueError('Thumbnail dimensions too large')
        img = ImageOps.exif_transpose(img).convert('RGB')
        img.thumbnail((320, 180))
        result = img.copy()
    with _lock:
        temporary = path.with_suffix('.tmp')
        result.save(temporary, format='JPEG')
        os.replace(temporary, path)
        files = sorted(root.glob('*.jpg'), key=lambda p:p.stat().st_mtime, reverse=True)
        size = 0
        for file in files:
            size += file.stat().st_size
            if size > MAX_BYTES:
                file.unlink(missing_ok=True)
    return result


def request(url, root, done):
    key = (str(root), url)
    with _lock:
        if key in _inflight:
            _inflight[key].append(done)
            return
        _inflight[key] = [done]
    def work():
        try:
            result = _load(url, root)
        except Exception:
            result = None
        with _lock:
            callbacks = _inflight.pop(key, [])
        for callback in callbacks:
            callback(result)
    _pool.submit(work)
