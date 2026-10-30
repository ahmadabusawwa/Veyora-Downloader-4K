"""Pinned English-Arabic bidirectional model installer. Only model downloads use the network."""
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
import zipfile
import uuid
from pathlib import Path
import requests
from .exceptions import TranslationError

MODEL_CATALOG = {
    ('en', 'ko'): {'pair': 'en_ko', 'url': 'https://data.argosopentech.com/argospm/v1/translate-en_ko-1_1.argosmodel', 'sha256': 'e03d8e65e6d44525ec5808c3409fcf8728c76c2c76925372b6d3dc3278de17fc', 'size_mib': 115, 'prefix': 'en_ko'},
    ('en', 'tr'): {'pair': 'en_tr', 'url': 'https://data.argosopentech.com/argospm/v1/translate-en_tr-1_5.argosmodel', 'sha256': '2d553a00880a0c21dea5b1c375535659e6bf18c9bf2ce9847c2a2fd2ff50316a', 'size_mib': 119, 'prefix': 'translate-en_tr-1_5'},
    ('ko', 'en'): {'pair': 'ko_en', 'url': 'https://data.argosopentech.com/argospm/v1/translate-ko_en-1_1.argosmodel', 'sha256': '6da8f3db6ca40f42b1875570a1c06856f6e17c7ef62845d85de217ba548c1471', 'size_mib': 113, 'prefix': 'ko_en'},
    ('tr', 'en'): {'pair': 'tr_en', 'url': 'https://data.argosopentech.com/argospm/v1/translate-tr_en-1_5.argosmodel', 'sha256': '15217905586561fac843efb5730aabff9a1534d5a9aa3f6ebcc0f9641394ac2d', 'size_mib': 115, 'prefix': 'translate-tr_en-1_5'},
    ('en', 'ar'): dict(pair='en_ar', sha256='e2a6e84337f7ebbb55f9dc61dcba3a861c0d786ae5a46fa198fd8d6473f5c775', size_mib=84),
    ('ar', 'en'): dict(pair='ar_en', sha256='bc98cd4e27ca1cebfae9b7086b2ebc635e4dbed45e7cb5f0891cb7d22feacfad', size_mib=78),
}
MODEL_SHA256 = MODEL_CATALOG[('en', 'ar')]['sha256']  # legacy import compatibility


def model_entry(source_lang='en', target_lang='ar'):
    try:
        return MODEL_CATALOG[(source_lang, target_lang)]
    except KeyError:
        raise TranslationError('No direct model for this language pair')


REQUIRED = ('model/model.bin', 'model/shared_vocabulary.txt', 'sentencepiece.model')
_install_lock = threading.Lock()


def config_root():
    return Path(os.environ.get('VEYORA_CONFIG_DIR', str(Path.home() / '.veyora')))


def model_directory(source_lang='en', target_lang='ar'):
    entry = model_entry(source_lang, target_lang)
    return config_root() / 'models' / 'translation' / (entry['pair'] + '-1.0')


def is_installed(path, source_lang='en', target_lang='ar'):
    try:
        return (all((path / name).is_file() and (path / name).stat().st_size > 0 for name in REQUIRED)
                and (path / 'VERIFIED_SHA256').read_text(encoding='ascii').strip()
                == model_entry(source_lang, target_lang)['sha256'])
    except (OSError, UnicodeError):
        return False



def _extract_verified(archive, destination, source_lang='en', target_lang='ar'):
    entry = model_entry(source_lang, target_lang)
    digest = hashlib.sha256()
    with open(archive, 'rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(data)
    if digest.hexdigest() != entry['sha256']:
        raise TranslationError('translation model checksum mismatch; the model was not installed')
    with zipfile.ZipFile(archive) as package:
        metadata = json.loads(package.read(entry.get('prefix', entry['pair']) + '/metadata.json'))
        if metadata.get('from_code') != source_lang or metadata.get('to_code') != target_lang:
            raise TranslationError('Wrong model language pair')
        # Explicit allowlist, no arbitrary archive paths, code or sentence-splitter weights.
        for name in (*REQUIRED, 'metadata.json', 'README.md'):
            info = package.getinfo(entry.get('prefix', entry['pair']) + '/' + name)
            if info.file_size > 200 * 1024 * 1024:
                raise TranslationError('Unexpected model entry size')
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.open(info) as source, target.open('wb') as out:
                shutil.copyfileobj(source, out)
    (destination / 'VERIFIED_SHA256').write_text(entry['sha256'], encoding='ascii')


def ensure_model(checkpoint=lambda: None, progress=lambda stage, fraction=None: None, source_lang='en', target_lang='ar'):
    entry = model_entry(source_lang, target_lang)
    direction = source_lang + ' -> ' + target_lang
    target = model_directory(source_lang, target_lang)
    checkpoint()
    if is_installed(target, source_lang, target_lang):
        return target
    progress('Waiting for translation model setup', None)
    while not _install_lock.acquire(timeout=.1):
        checkpoint()
    try:
        checkpoint()
        if is_installed(target, source_lang, target_lang):
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='en-ar-install-', dir=target.parent) as work:
            work = Path(work)
            archive = work / 'model.argosmodel'
            local = os.environ.get('VEYORA_' + entry['pair'].upper() + '_MODEL_ARCHIVE')
            if not local and (source_lang, target_lang) == ('en', 'ar'):
                local = os.environ.get('VEYORA_AR_MODEL_ARCHIVE')
            if local:
                shutil.copyfile(local, archive)
            else:
                errors = []
                for host in ('https://data.argosopentech.com/argospm/v1/', 'https://argos-net.com/v1/'):
                    filename = entry.get('url', 'translate-' + entry['pair'] + '-1_0.argosmodel').rsplit('/', 1)[-1]
                    url = host + filename
                    checkpoint()
                    progress(f'Downloading {direction} model (about {entry["size_mib"]} MiB, first use only)', 0)
                    try:
                        start, last, size = time.monotonic(), 0.0, 0
                        with requests.get(url, stream=True, timeout=(10, 20)) as response:
                            response.raise_for_status()
                            total = int(response.headers.get('Content-Length') or 0)
                            with archive.open('wb') as stream:
                                for chunk in response.iter_content(128 * 1024):
                                    checkpoint()
                                    now = time.monotonic()
                                    if now - start > 600:
                                        raise requests.Timeout('translation model download exceeded 10 minutes')
                                    stream.write(chunk)
                                    size += len(chunk)
                                    if size > 150 * 1024 * 1024:
                                        raise TranslationError('translation model download exceeded size limit')
                                    if now - last >= .2:
                                        progress(f'Downloading {direction} model: {size/1048576:.1f} MiB', min(1, size/total) if total else None)
                                        last = now
                        break
                    except requests.RequestException as exc:
                        errors.append(type(exc).__name__)
                else:
                    raise TranslationError('Could not download translation model. Check internet, then Retry. Source transcript is retained. ' + ', '.join(errors))
            checkpoint()
            progress('Verifying and installing translation model', None)
            staging = work / 'ready'
            _extract_verified(archive, staging, source_lang, target_lang)
            checkpoint()
            # Another process may have installed the model while this one downloaded.
            if is_installed(target, source_lang, target_lang):
                return target
            if target.exists():
                # Preserve incomplete files, then publish the fully verified replacement.
                damaged = target.with_name(target.name + '.incomplete-' + uuid.uuid4().hex[:8])
                os.replace(target, damaged)
            os.replace(staging, target)
        return target
    finally:
        _install_lock.release()


def translation_route(source_lang, target_lang):
    languages = {'ar', 'en', 'tr', 'ko'}
    if source_lang not in languages or target_lang not in languages or source_lang == target_lang:
        raise TranslationError('Supported translation directions require different languages among Arabic, English, Turkish and Korean')
    if (source_lang, target_lang) in MODEL_CATALOG:
        return [(source_lang, target_lang)]
    return [(source_lang, 'en'), ('en', target_lang)]
