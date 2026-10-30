"""Real CPU recognition/translation validation with locally generated licensed test speech.

Downloads are deliberately separate: run prepare_translation.py --speech first.
Run with --model-root, --espeak and --espeak-data; report includes scope limitations.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def block_native_connections():
    """Linux test guard: block connect() in native libraries as well as Python."""
    if not sys.platform.startswith('linux'):
        return 'Python socket guard only; use a firewall for native Windows network isolation'
    import ctypes
    import ctypes.util
    library = ctypes.util.find_library('seccomp')
    if not library:
        raise RuntimeError('Native network isolation requires libseccomp for this Linux test')
    seccomp = ctypes.CDLL(library)
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    context = seccomp.seccomp_init(0x7fff0000)  # Allow all unrelated syscalls.
    if not context:
        raise RuntimeError('Cannot allocate network isolation filter')
    try:
        number = seccomp.seccomp_syscall_resolve_name(b'connect')
        if number < 0 or seccomp.seccomp_rule_add(context, 0x00050001, number, 0) != 0:
            raise RuntimeError('Cannot configure network isolation filter')
        if seccomp.seccomp_load(context) != 0:
            raise RuntimeError('Cannot activate native network isolation')
    finally:
        seccomp.seccomp_release(context)
    return 'Native connect() blocked with seccomp, plus Python socket guard'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-root', required=True)
    parser.add_argument('--espeak', default='espeak-ng')
    parser.add_argument('--espeak-data')
    parser.add_argument('--output', default='repair-integration.json')
    parser.add_argument('--long-seconds', type=int, default=600)
    args = parser.parse_args()
    os.environ['VEYORA_CONFIG_DIR'] = str(Path(args.model_root).resolve())
    os.environ['HF_HUB_OFFLINE'] = '1'
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    from translator.transcription import Transcriber, release_speech_model
    from translator.translation_provider import TranslatorProvider, release_translation_models
    from translator.pipeline import TranslationPipeline
    from translator.subtitle_generator import parse_srt
    from translator.video_renderer import run_ffmpeg, get_ffprobe_info
    samples = {'en': 'Hello world. This is a short video about downloading files.',
               'ar': 'مرحبا بالعالم. هذا فيديو قصير عن تحميل الملفات.',
               'tr': 'Merhaba dünya. Bugün hava çok güzel.',
               'ko': '안녕하세요. 오늘 날씨가 좋습니다.'}
    report = {'ok': False, 'scope': 'Synthetic espeak-ng speech, CPU inference. Not a human speech accuracy certification. Long media has speech at the start and silence afterwards.',
              'network': 'All socket connect calls blocked during recognition and translation', 'speech': [], 'media': []}

    def blocked(*a, **kw):
        raise AssertionError('Unexpected network during offline validation')

    report['native_network_guard'] = block_native_connections()
    original_connect = socket.socket.connect
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix='veyora-validation-') as folder:
            root = Path(folder)
            for lang, text in samples.items():
                audio = root / (lang + '.wav')
                command = [args.espeak]
                if args.espeak_data:
                    command.append('--path=' + args.espeak_data)
                subprocess.run(command + ['-v', lang, '-s', '135', '-w', str(audio), text],
                               check=True, capture_output=True, timeout=30)
            socket.socket.connect = blocked
            for lang in samples:
                start = time.monotonic()
                segments, info = Transcriber(model_size='base', language=lang).transcribe(str(root / (lang + '.wav')))
                transcript = ' '.join(c.text.strip() for c in segments)
                if not transcript:
                    raise RuntimeError('No recognized speech: ' + lang)
                release_speech_model()
                item = {'source': lang, 'transcript': transcript, 'translations': {}, 'warnings': []}
                report['speech'].append(item)
                for target in samples:
                    if target == lang:
                        continue
                    provider = TranslatorProvider(lang, target)
                    translated = provider.translate(transcript)
                    if not translated.strip() or translated == transcript:
                        item['warnings'].append('Empty or unchanged translation for ' + target)
                    item['translations'][target] = translated
                    release_translation_models()
                item['seconds'] = round(time.monotonic() - start, 2)
                item['status'] = 'warning' if item['warnings'] else 'completed'
                print('Actual recognition + 3 translations:', lang, item['status'], flush=True)
            for duration, mode in [(8, 'burn'), (args.long_seconds, 'embed')]:
                video = root / f'فيديو عربي {duration}.mp4'
                run_ffmpeg(['-f', 'lavfi', '-i', f'color=s=160x90:r=1:d={duration}',
                            '-i', root / 'en.wav', '-af', 'apad', '-t', str(duration),
                            '-c:v', 'libx264', '-threads', '2', '-c:a', 'aac', video])
                start = time.monotonic()
                outputs = TranslationPipeline(video, root / 'output').run(
                    mode=mode, source_lang='en', target_lang='ar')
                cues = parse_srt(outputs['subtitle'])
                if not all(c.text.strip() and 0 <= c.start <= c.end <= duration + 1 for c in cues):
                    raise RuntimeError('Invalid translated subtitle cues')
                streams = get_ffprobe_info(outputs['video'])['streams']
                assert any(s['codec_type'] == 'video' for s in streams)
                if mode == 'embed':
                    assert any(s['codec_type'] == 'subtitle' and s['tags']['language'] == 'ara' for s in streams)
                report['media'].append({'duration': duration, 'mode': mode, 'cues': len(cues),
                    'subtitle': [dict(start=c.start, end=c.end, text=c.text) for c in cues],
                    'seconds': round(time.monotonic() - start, 2)})
                print('PASS actual video pipeline:', duration, mode, flush=True)
        report['ok'] = all(not item['warnings'] for item in report['speech'])
        report['media_ok'] = True
    except Exception as exc:
        report['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        socket.socket.connect = original_connect
        release_speech_model()
        release_translation_models()
        report['seconds'] = round(time.monotonic() - started, 2)
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
