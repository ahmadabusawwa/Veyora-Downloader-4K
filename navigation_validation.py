"""Actual installed playlist downloads and bounded cached-navigation stress tests."""
import functools
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import threading
import time

PAGES = ('Dashboard', 'Playlist', 'Downloads', 'Translation', 'Convert', 'History', 'Settings')


def press_page(app, name):
    if name in app._nav_buttons:
        app._nav_buttons[name].invoke()
    else:
        key = {'Playlist': 'playlists', 'Convert': 'convert', 'History': 'history'}[name]
        app._sidebar_buttons[key].invoke()
    if app.active_tab != name:
        raise RuntimeError('Navigation opened the wrong page: ' + name)


def widget_count(widget):
    return 1 + sum(widget_count(child) for child in widget.winfo_children())


def pending_callbacks(app):
    return len(app.tk.splitlist(app.tk.call('after', 'info')))


def memory_bytes():
    if os.name != 'nt':
        return int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
                'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    value = Counters()
    value.cb = ctypes.sizeof(value)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(value), value.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return value.WorkingSetSize


def run_navigation_review(media, cancel_media, report_directory):
    from desktop_ui import DesktopApp
    from main import APP_VERSION
    directory = Path(report_directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    web = directory / 'playlist-source'
    web.mkdir(exist_ok=True)
    shutil.copyfile(media, web / 'first.mp4')
    shutil.copyfile(cancel_media, web / 'second.mp4')
    from PIL import Image
    Image.new('RGB',(160,90),(240,180,20)).save(web/'poster.png')
    (web / 'index.html').write_text('<html><head><title>Authorized local playlist</title></head><body>'
        '<video controls poster="poster.png" src="first.mp4"></video><video controls poster="poster.png" src="second.mp4"></video></body></html>', encoding='utf8')
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(web)))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True, name='playlist-local-server')
    server_thread.start()
    app = DesktopApp()
    app.settings.update(ui_language='en', download_subs=False, save_thumbnail=False)
    app.sub_var.set(False)
    app.thumb_var.set(False)
    app.desc_var.set(False)
    app.split_var.set(False)
    app.clip_var.set(False)
    app.selected_folder = str(directory / 'playlist-downloads')
    report = dict(ok=False, version=APP_VERSION, backend='Actual installed GUI, real yt-dlp, local HTTP playlist', errors=[])
    state = dict(phase='warm', index=0, rounds=0, deadline=time.monotonic()+180,
                 last_tick=None, gaps=[], nav_times=[], baseline=None, settle_until=0)

    def write_close(error=None):
        if error:
            report['errors'].append(str(error))
        report['ok'] = not report['errors'] and report.get('playlist_downloads_ok', False) and report.get('navigation_ok', False)
        report['ui_max_gap_seconds'] = max(state['gaps'], default=0)
        (directory / 'navigation-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        app._on_close()

    def baseline():
        return dict(widgets=widget_count(app), callbacks=pending_callbacks(app),
                    threads=len(threading.enumerate()), memory_bytes=memory_bytes(),
                    key_binding=app.bind_all('<Key>'), wheel_binding=app.bind_all('<MouseWheel>'))

    def poll():
        try:
            now = time.monotonic()
            if now > state['deadline']:
                raise RuntimeError('Installed navigation review timeout')
            if state['last_tick'] is not None:
                state['gaps'].append(now-state['last_tick'])
            state['last_tick'] = now
            if state['phase'] == 'warm':
                press_page(app, PAGES[state['index']])
                state['index'] += 1
                if state['index'] == len(PAGES):
                    press_page(app, 'Translation')
                    app._local_task_controls['path'].set(str(media))
                    press_page(app, 'Playlist')
                    app._playlist_controls['url'].set(f'http://127.0.0.1:{server.server_port}/index.html')
                    app._playlist_controls['load'].invoke()
                    state['phase'] = 'playlist_loading'
            elif state['phase'] == 'playlist_loading' and not app._playlist_state['busy']:
                entries = app._playlist_state['entries']
                if len(entries) != 2 or len({x['url'] for x in entries}) != 2:
                    raise RuntimeError('Actual playlist did not return two distinct media entries')
                report['playlist_entries'] = entries
                app._playlist_controls['download'].invoke()
                state['phase'] = 'playlist_downloading'
            elif state['phase'] == 'playlist_downloading':
                tasks = app.queue_manager.get_tasks_by_status()
                if len(tasks) == 2 and all(t['status'] in app.queue_manager.TERMINAL for t in tasks):
                    if not all(t['status'] == 'Completed' for t in tasks):
                        raise RuntimeError('Actual selected playlist download failed: ' + str(tasks))
                    def digest(path):
                        with Path(path).open('rb') as f:
                            return hashlib.file_digest(f, 'sha256').hexdigest()
                    if {digest(t['downloaded_file']) for t in tasks} != {digest(media), digest(cancel_media)}:
                        raise RuntimeError('Downloaded playlist bytes differ from real input media')
                    report['playlist_downloads_ok'] = True
                    if not all(t.get('thumbnail') for t in tasks):
                        raise RuntimeError('Playlist lost its original thumbnail metadata')
                    state.update(phase='warm_downloaded', index=0)
            elif state['phase'] == 'warm_downloaded':
                press_page(app, PAGES[state['index']])
                state['index'] += 1
                if state['index'] == len(PAGES):
                    state.update(phase='settle', settle_until=now+.5)
            elif state['phase'] == 'settle' and now >= state['settle_until']:
                app.show_tab('Downloads')
                if not all(getattr(card,'_thumbnail_url',None) for card in app.card_widgets.values()):
                    raise RuntimeError('Original thumbnails were not requested by actual download cards')
                report['original_thumbnails_requested'] = True
                state['baseline'] = baseline()
                state.update(phase='repeat', index=0)
            elif state['phase'] == 'repeat':
                name = PAGES[state['index']]
                host = app.pages.pages[name]['host']
                for _ in range(20):
                    start = time.monotonic()
                    press_page(app, name)
                    state['nav_times'].append(time.monotonic()-start)
                    if app.pages.pages[name]['host'] is not host:
                        raise RuntimeError('A repeated click rebuilt the cached page')
                state['index'] += 1
                if state['index'] == len(PAGES):
                    state.update(phase='rapid', rounds=0)
            elif state['phase'] == 'rapid':
                for name in PAGES:
                    press_page(app, name)
                state['rounds'] += 1
                if state['rounds'] == 20:
                    state.update(phase='measure', settle_until=now+.5)
            elif state['phase'] == 'measure' and now >= state['settle_until']:
                after = baseline()
                before = state['baseline']
                report.update(before=before, after=after, build_counts=app.pages.build_counts,
                              repeated_clicks_per_page=20, rapid_rounds=20,
                              max_navigation_call_seconds=max(state['nav_times']),
                              memory_growth_bytes=after['memory_bytes']-before['memory_bytes'])
                if after['widgets'] != before['widgets']:
                    raise RuntimeError('Widget count grew after cached navigation')
                if after['callbacks'] > before['callbacks']+2 or after['threads'] > before['threads']:
                    raise RuntimeError('Callback/thread count grew after navigation')
                if after['key_binding'] != before['key_binding'] or after['wheel_binding'] != before['wheel_binding']:
                    raise RuntimeError('Global bindings duplicated after navigation')
                if report['memory_growth_bytes'] > 32*1024*1024:
                    raise RuntimeError('Parent working set grew by more than 32 MiB after navigation')
                if any(v != 1 for v in app.pages.build_counts.values()) or app.local_tasks.launch_count:
                    raise RuntimeError('Navigation rebuilt a page or started an unexpected local job')
                press_page(app, 'Translation')
                if app._local_task_controls['path'].get() != str(media):
                    raise RuntimeError('Selected file disappeared after navigation')
                report['navigation_ok'] = True
                write_close()
                return
            app.after(50, poll)
        except Exception as exc:
            write_close(exc)

    app.report_callback_exception = lambda *args: report['errors'].append(str(args))
    app.after(100, poll)
    app.mainloop()
    server.shutdown()
    server.server_close()
    server_thread.join(timeout=3)
    return 0 if report['ok'] else 1
