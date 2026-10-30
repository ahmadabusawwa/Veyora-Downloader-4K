"""Prepare both offline translation directions and verify real CPU inference."""
import re
import time
from translator.translation_provider import TranslatorProvider


def main():
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
        print('PASS: real local ' + source + ' -> ' + target + ' translation; no Google service.', flush=True)


if __name__ == '__main__':
    main()
