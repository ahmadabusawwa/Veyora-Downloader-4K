"""Drive the installed GUI against actual speech/video. No mocked backend or inference.

Only invoked by --review-video. The Windows harness installs program-specific
outbound firewall rules before launching this command, after preparing models.
"""
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import re
import time


def _sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run_video_review(media_path, cancel_media_path, report_directory):
    from desktop_ui import DesktopApp
    from main import APP_VERSION
    from translator.subtitle_generator import parse_srt
    from translator.video_renderer import get_ffprobe_info, run_ffmpeg

    directory = Path(report_directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    report_file = directory / 'real-video-results.json'
    report = dict(ok=False, version=APP_VERSION, backend='Actual installed GUI + spawned Whisper/Argos/FFmpeg',
                  scope='Synthetic English speech translated to Arabic; not a human speech accuracy certification',
                  input_sha256=_sha256(media_path), cancellation_input_sha256=_sha256(cancel_media_path),
                  errors=[], phases=[], window_actions=[], network='Program-specific Windows outbound firewall blocks; HF_HUB_OFFLINE=1')
    if os.environ.get('VEYORA_REVIEW_NETWORK_BLOCKED') != '1' or os.environ.get('HF_HUB_OFFLINE') != '1':
        raise RuntimeError('Actual speech review requires the offline Windows firewall harness')
    if report['input_sha256'] == report['cancellation_input_sha256']:
        raise RuntimeError('Cancellation media must have a different cache key')

    app = DesktopApp()
    app.settings.update(ui_language='en', save_original_subtitles=True)
    from navigation_validation import PAGES, press_page, memory_bytes, pending_callbacks, widget_count
    for page in PAGES:
        press_page(app, page)
    app.selected_folder = str(directory / 'translated')
    app.settings['auto_update_check'] = False
    app.report_callback_exception = lambda *error: report['errors'].append(str(error))
    started = time.monotonic()
    state = dict(phase='starting', last_tick=None, ticks=[], stage=None, recognize_started=None,
                 cancel_sent=None, window_step=None, window_due=None, window_done=False, window_cycles=0, nav_steps=0, task_id=None)
    active = [True]

    def save_and_close(error=None):
        if not active[0]:
            return
        active[0] = False
        if error:
            report['errors'].append(str(error))
        report['seconds'] = round(time.monotonic() - started, 3)
        report['page_build_counts'] = dict(app.pages.build_counts)
        report['local_job_launches'] = app.local_tasks.launch_count
        report['navigation_during_speech_steps'] = state['nav_steps']
        report['minimize_restore_cycles'] = state['window_cycles']
        gaps = state['ticks']
        report['ui_timer'] = dict(samples=len(gaps), max_gap_seconds=round(max(gaps, default=0), 4),
            p95_gap_seconds=round(sorted(gaps)[min(len(gaps)-1, int(len(gaps)*.95))], 4) if gaps else None)
        report['ok'] = bool(report.get('video_translation_ok') and report.get('cancellation_ok')
                            and report.get('window_actions_ok') and not report['errors'])
        if not gaps or max(gaps) > 1.5:
            report['ok'] = False
            report['errors'].append('UI heartbeat gap exceeded 1.5 seconds or no samples collected')
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        app._on_close()

    def launch(path, mode):
        app.show_tab('Translation')
        controls = app._local_task_controls
        controls['path'].set(str(path))
        controls['source'].set(app._label_for_lang('en', allow_auto=True))
        controls['target'].set(app._label_for_lang('ar', allow_auto=False))
        controls['mode'].set(app._subtitle_mode_to_display(mode))
        controls['start'].invoke()
        state['task_id'] = app.local_tasks.snapshot('Translation').id
        if not app._local_running or controls['start'].cget('state') != 'disabled':
            raise RuntimeError('Actual Start command did not acknowledge the job')

    def inspect_completed_video():
        result = getattr(app, '_local_result', None)
        if not result or getattr(app, '_local_error', None):
            raise RuntimeError('Actual video job failed: ' + str(getattr(app, '_local_error', None)))
        source = parse_srt(result['source_subtitle'])
        translated = parse_srt(result['subtitle'])
        source_text = ' '.join(c.text for c in source).lower()
        target_text = ' '.join(c.text for c in translated)
        if sum(word in source_text for word in ('hello', 'weather', 'download', 'subtitles')) < 2:
            raise RuntimeError('Actual English speech recognition did not recover expected sample words')
        if sum(word in target_text for word in ('مرحبا', 'مرحباً', 'الطقس', 'جميل', 'تنزيل', 'تحميل', 'ترجمة')) < 2:
            raise RuntimeError('Actual translation did not recover expected Arabic sample words')
        if len(source) != len(translated) or not source:
            raise RuntimeError('Source and translated cue counts differ')
        for a, b in zip(source, translated):
            if not (0 <= b.start <= b.end and abs(a.start-b.start) < .002 and abs(a.end-b.end) < .002):
                raise RuntimeError('Translated SRT timing does not match the recognized speech')
        video = Path(result['video'])
        if video.suffix.lower() != '.mp4' or video.stat().st_size == 0:
            raise RuntimeError('Actual MP4 output missing')
        info = get_ffprobe_info(video)
        original = get_ffprobe_info(media_path)
        if abs(float(info['format']['duration']) - float(original['format']['duration'])) > 1:
            raise RuntimeError('Rendered MP4 duration changed')
        if not any(s['codec_type'] == 'video' for s in info['streams']):
            raise RuntimeError('Rendered MP4 has no video stream')
        if not any(s['codec_type'] == 'audio' for s in info['streams']):
            raise RuntimeError('Rendered MP4 has no audio stream')
        # The fixture is solid blue, so white pixels at a cue midpoint must
        # come from the burned subtitle rather than the source video.
        from PIL import Image
        frame = directory / 'translated-frame.png'
        midpoint = (translated[0].start + translated[0].end) / 2
        run_ffmpeg(['-ss', str(midpoint), '-i', video, '-frames:v', '1', frame])
        with Image.open(frame) as image:
            white_pixels = sum(r > 160 and g > 160 and b > 160 for r, g, b in image.convert('RGB').getdata())
        if white_pixels < 10:
            raise RuntimeError('No visible burned subtitle pixels in the actual MP4 sample frame')
        report['burned_subtitle_white_pixels'] = white_pixels
        report['frame_sha256'] = _sha256(frame)
        report.update(video_translation_ok=True, source_transcript=source_text, arabic_translation=target_text,
            cue_count=len(translated), duration_seconds=float(info['format']['duration']),
            outputs={key: dict(path=str(Path(value).relative_to(directory)), sha256=_sha256(value),
                             size=Path(value).stat().st_size) for key, value in result.items()})

    def windows_actions(now):
        if state['window_step'] == 'minimize' and now >= state['window_due']:
            if app.state() != 'iconic':
                raise RuntimeError('Window did not minimize during real processing')
            report['window_actions'].append(dict(action='minimized', while_processing=app._local_running))
            app.deiconify()
            state.update(window_step='maximize', window_due=now+.35)
        elif state['window_step'] == 'maximize' and now >= state['window_due']:
            app.state('zoomed')
            state.update(window_step='verify_maximize', window_due=now+.35)
        elif state['window_step'] == 'verify_maximize' and now >= state['window_due']:
            if app.state() != 'zoomed':
                raise RuntimeError('Window did not maximize during real processing')
            report['window_actions'].append(dict(action='maximized', while_processing=app._local_running))
            app.state('normal')
            app.geometry('1280x820')
            report['window_actions'].append(dict(action='restored', while_processing=app._local_running))
            state['window_cycles'] += 1
            if state['window_cycles'] < 20:
                state.update(window_step='next_cycle', window_due=now+.2)
            else:
                state.update(window_step=None, window_done=True)
                report['window_actions_ok'] = all(x['while_processing'] for x in report['window_actions'])
        elif state['window_step'] == 'next_cycle' and now >= state['window_due']:
            app.iconify()
            state.update(window_step='minimize', window_due=now+.35)


    def poll():
        if not active[0]:
            return
        try:
            now = time.monotonic()
            if state['last_tick'] is not None:
                state['ticks'].append(now-state['last_tick'])
            state['last_tick'] = now
            if now-started > 600:
                raise RuntimeError('Real video review exceeded ten minutes')
            if report['errors']:
                raise RuntimeError('Unhandled GUI callback failure')
            stage = getattr(app, '_local_status', ('', None))[0]
            if stage != state['stage']:
                report['phases'].append(dict(seconds=round(now-started, 3), phase=state['phase'], stage=stage))
                state['stage'] = stage
            if state['phase'] == 'starting':
                launch(media_path, 'burn')
                state['phase'] = 'translating'
            elif state['phase'] == 'translating':
                if app._local_running and 'Recognizing' in stage and state['recognize_started'] is None:
                    state['recognize_started'] = now
                    app.iconify()
                    state.update(window_step='minimize', window_due=now+.35)
                windows_actions(now)
                if app._local_running and state['recognize_started'] is not None and state['nav_steps'] < 140:
                    name = PAGES[state['nav_steps'] % len(PAGES)]
                    for _ in range(20):
                        press_page(app, name)
                    press_page(app, 'Translation')
                    app._refresh_local_tasks(force=True)
                    snapshot = app.local_tasks.snapshot('Translation')
                    if snapshot.id != state['task_id'] or app.local_tasks.launch_count != 1:
                        raise RuntimeError('Navigation duplicated/replaced the real translation task')
                    if app._local_task_controls['path'].get() != str(media_path):
                        raise RuntimeError('Real input file disappeared while navigating during speech')
                    if snapshot.status == 'running' and app._local_task_controls['cancel'].cget('state') != 'normal':
                        raise RuntimeError('Return to translation lost the task cancellation control')
                    # The disabled real Start command must remain harmless on repeated invocation.
                    for _ in range(20):
                        app._local_task_controls['start'].invoke()
                    state['nav_steps'] += 1
                if not app._local_running:
                    if state['nav_steps'] != 140 or not state['window_done']:
                        raise RuntimeError('Real processing ended before minimize/maximize checks completed')
                    inspect_completed_video()
                    audit = directory / 'audit' / 'speech-loads.jsonl'
                    loads = [json.loads(line) for line in audit.read_text(encoding='utf8').splitlines()]
                    if len(loads) != 1:
                        raise RuntimeError('Speech model was loaded again during navigation')
                    # A different real file forces fresh speech recognition instead of cache reuse.
                    app.selected_folder = str(directory / 'cancelled-output')
                    launch(cancel_media_path, 'burn')
                    state['phase'] = 'cancelling_real_job'
                    state['last_tick'] = time.monotonic()
            elif state['phase'] == 'cancelling_real_job':
                if state['cancel_sent'] is None:
                    if not app._local_running:
                        raise RuntimeError('Cancellation job ended before real recognition was observed')
                    if re.search(r'Recognizing.*speech: \d', stage):
                        press_page(app, 'Downloads')
                        press_page(app, 'Settings')
                        press_page(app, 'Translation')
                        if app.local_tasks.snapshot('Translation').id != state['task_id']:
                            raise RuntimeError('Cancellation on return targeted a different task')
                        app._local_task_controls['cancel'].invoke()
                        state['cancel_sent'] = now
                        report['cancel_during_stage'] = stage
                elif not app._local_running:
                    report['cancellation_seconds'] = round(now-state['cancel_sent'], 3)
                    error = str(getattr(app, '_local_error', ''))
                    remaining = [p.pid for p in multiprocessing.active_children() if p.is_alive()]
                    report['remaining_workers_after_cancel'] = remaining
                    if getattr(app, '_local_result', None) or 'cancel' not in error.lower() or remaining:
                        raise RuntimeError('Cancellation did not stop the actual job cleanly: ' + error)
                    if report['cancellation_seconds'] > 12:
                        raise RuntimeError('Cancellation took longer than twelve seconds')
                    audit = directory / 'audit' / 'speech-loads.jsonl'
                    loads = [json.loads(line) for line in audit.read_text(encoding='utf8').splitlines()]
                    if len(loads) != 2 or app.local_tasks.launch_count != 2:
                        raise RuntimeError('Navigation changed model-load or task-launch counts')
                    report['actual_speech_model_loads'] = loads
                    report['cancellation_after_navigation'] = True
                    report['cancellation_ok'] = True
                    save_and_close()
                    return
            app.after(50, poll)
        except Exception as exc:
            save_and_close(exc)

    app.after(200, poll)
    app.mainloop()
    return 0 if report['ok'] else 1
