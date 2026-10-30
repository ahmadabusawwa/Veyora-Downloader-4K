"""Prepare both offline translation directions and verify real CPU inference."""
import re
import time
from translator.translation_provider import TranslatorProvider, release_translation_models


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--speech', action='store_true', help='Also download base multilingual and base.en speech models')
    parser.add_argument('--speech-model', nargs='+', choices=['base', 'base.en', 'small', 'medium'], default=['base', 'base.en'])
    args = parser.parse_args()
    if args.speech:
        from faster_whisper.utils import download_model
        from translator.offline_model import config_root
        for name in args.speech_model:
            print('Preparing speech model: ' + name, flush=True)
            download_model(name, cache_dir=str(config_root() / 'models'))
    previous = [0.0]
    def progress(stage, fraction=None):
        now = time.monotonic()
        if fraction is None or now - previous[0] > 1:
            print(stage, flush=True)
            previous[0] = now
    for source, target, text in [('en', 'ar', 'Hello world.'), ('ar', 'en', 'مرحبا بالعالم'), ('en', 'tr', 'Hello world.'), ('tr', 'en', 'Merhaba dünya.'), ('en', 'ko', 'Hello world.'), ('ko', 'en', '안녕하세요.')]:
        provider = TranslatorProvider(source, target)
        provider.prepare(progress=progress)
        value = provider.translate(text)
        valid = any('\u0600' <= c <= '\u06ff' for c in value) if target == 'ar' else (any('가' <= c <= '힣' for c in value) if target == 'ko' else bool(re.search('[A-Za-z]', value)))
        if not valid:
            raise RuntimeError('Offline model did not produce expected language: ' + source + ' -> ' + target)
        release_translation_models()
        print('PASS: real local ' + source + ' -> ' + target + ' translation; no Google service.', flush=True)


if __name__ == '__main__':
    main()
