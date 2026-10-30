import threading
import time
from pathlib import Path
import pytest
from local_tasks import LocalTaskManager


def test_central_job_survives_views_and_rejects_duplicate_launches(tmp_path):
    manager = LocalTaskManager()
    entered = threading.Event()
    def runner(*args, checkpoint, progress, **kwargs):
        entered.set()
        progress('Recognizing speech', .25)
        while True:
            checkpoint()
            time.sleep(.01)
    tid = manager.start('Translation', 'عربي.mp4', tmp_path, 'en', 'ar', 'burn', runner=runner)
    assert entered.wait(2)
    for _ in range(20):
        assert manager.start('Translation', 'other.mp4', tmp_path, 'en', 'ar', 'burn', runner=runner) is None
    snapshot = manager.snapshot('Translation')
    assert snapshot.id == tid and snapshot.path == 'عربي.mp4' and snapshot.fraction == .25
    assert not manager.cancel('Convert')
    assert manager.cancel('Translation')
    deadline = time.monotonic()+3
    while manager.busy and time.monotonic() < deadline:
        threading.Event().wait(.01)
    assert manager.snapshot('Translation').status == 'cancelled'
    assert manager.launch_count == 1 and not manager.busy
    manager.close()


def test_forms_and_completed_results_are_independent_of_page_lifetime(tmp_path):
    manager = LocalTaskManager()
    manager.save_form('Translation', path='selected.mp4', source='tr', target='ar', mode='separate')
    manager.save_form('Convert', path='other.mp4', mode='MP3')
    done = threading.Event()
    def runner(*args, **kwargs):
        done.set()
        return {'subtitle': 'result.srt'}
    tid = manager.start('Translation', 'selected.mp4', tmp_path, 'tr', 'ar', 'separate', runner=runner)
    assert done.wait(2)
    deadline=time.monotonic()+2
    while manager.busy and time.monotonic() < deadline:
        threading.Event().wait(.01)
    assert manager.snapshot('Translation').result == {'subtitle':'result.srt'}
    assert manager.snapshot('Translation').id == tid
    assert manager.form('Translation')['path'] == 'selected.mp4'
    assert manager.form('Convert')['path'] == 'other.mp4'
    assert not manager.cancel('Translation')  # terminal result cannot become cancelling


def test_cached_pages_keep_file_settings_and_one_view_instance(monkeypatch, tmp_path):
    import main
    from desktop_ui import DesktopApp
    from navigation_validation import PAGES, press_page, widget_count, pending_callbacks
    monkeypatch.setitem(main.DEFAULT_SETTINGS, 'auto_update_check', False)
    app = DesktopApp()
    try:
        for page in PAGES:
            press_page(app, page)
        press_page(app, 'Translation')
        controls = app._local_task_controls
        controls['path'].set(str(tmp_path/'فيديو.mp4'))
        controls['source'].set(app._label_for_lang('tr', allow_auto=True))
        controls['target'].set(app._label_for_lang('ar', allow_auto=False))
        controls['mode'].set(app._subtitle_mode_to_display('burn'))
        hosts = {key: item['host'] for key,item in app.pages.pages.items()}
        app.after(200, app.quit)
        app.mainloop()
        count = widget_count(app)
        callbacks = pending_callbacks(app)
        for page in PAGES:
            for _ in range(20):
                press_page(app, page)
                assert app.pages.pages[page]['host'] is hosts[page]
        press_page(app, 'Translation')
        assert app._local_task_controls is controls
        assert controls['path'].get() == str(tmp_path/'فيديو.mp4')
        assert app.local_tasks.form('Translation')['source'] == 'tr'
        assert app.local_tasks.form('Translation')['mode'] == 'burn'
        assert widget_count(app) == count
        assert pending_callbacks(app) <= callbacks+2
        assert app.pages.build_counts == {page:1 for page in PAGES}
        assert app.local_tasks.launch_count == 0
        app.toggle_language()
        assert app.local_tasks.form('Translation')['path'] == str(tmp_path/'فيديو.mp4')
        assert app._local_task_controls['path'].get() == str(tmp_path/'فيديو.mp4')
    finally:
        app._on_close()


def test_playlist_button_opens_distinct_page(monkeypatch):
    import main
    from desktop_ui import DesktopApp
    monkeypatch.setitem(main.DEFAULT_SETTINGS, 'auto_update_check', False)
    app = DesktopApp()
    try:
        original = app.url_entry
        app._sidebar_buttons['playlists'].invoke()
        assert app.active_tab == 'Playlist'
        assert app._playlist_controls['url'] is not original
        host = app.pages.pages['Playlist']['host']
        for _ in range(20):
            app._sidebar_buttons['playlists'].invoke()
        assert app.pages.pages['Playlist']['host'] is host
        assert app.pages.build_counts['Playlist'] == 1
    finally:
        app._on_close()
