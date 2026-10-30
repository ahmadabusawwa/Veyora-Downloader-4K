import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
import customtkinter as ctk
from tkinter import messagebox
from .core import UpdateClient

class UpdateUI:
    def __init__(self, app, version, config_dir):
        self.app = app
        self.directory = Path(config_dir)
        self.client = UpdateClient(version, self.directory/'updates')
        self.busy = False
        self.cancel = threading.Event()
        journal = self.directory / 'update-status.json'
        if journal.exists():
            import json
            try:
                state = json.loads(journal.read_text(encoding='utf8'))
                if state.get('state') == 'handed-off':
                    from .core import version as parse_version
                    if parse_version(version) >= parse_version(state['version']):
                        state['state'] = 'confirmed'
                        journal.write_text(json.dumps(state), encoding='utf8')
                    else:
                        self.app.after(2500, lambda:messagebox.showinfo('Updates', 'The previous update was not completed. Your data is preserved. Use Check for Updates to retry.'))
            except (ValueError, KeyError, OSError):
                pass

    def dispatch(self, callback):
        self.app._ui_callbacks.put(callback)

    def check(self, manual=True):
        if self.busy:
            return
        self.busy = True
        prereleases = self.app.settings.get('allow_prereleases', False)
        def work():
            try:
                release = self.client.check(prereleases)
                self.dispatch(lambda:self.show_release(release, manual))
            except Exception as exc:
                error = str(exc)
                if manual:
                    self.dispatch(lambda:messagebox.showerror('Updates', error))
            finally:
                self.busy = False
        threading.Thread(target=work, daemon=True, name='update-check').start()

    def show_release(self, release, manual):
        if not release:
            if manual:
                messagebox.showinfo('Updates', 'You are using the latest supported release.')
            return
        w = ctk.CTkToplevel(self.app)
        w.title('Veyora Pro — verified update ' + release['tag'])
        w.geometry('600x440')
        notes = ctk.CTkTextbox(w, wrap='word')
        notes.pack(fill='both', expand=True, padx=20, pady=15)
        notes.insert('1.0', release['notes'])
        notes.configure(state='disabled')
        bar = ctk.CTkProgressBar(w)
        bar.pack(fill='x', padx=20, pady=10)
        bar.set(0)
        status = ctk.CTkLabel(w, text='Signed update verified. Download to continue.')
        status.pack()
        def download():
            if self.busy:return
            self.busy = True
            self.cancel.clear()
            button.configure(state='disabled')
            previous = [0.0]
            def progress(value):
                now = time.monotonic()
                if value < 1 and now - previous[0] < .1:return
                previous[0] = now
                self.dispatch(lambda:bar.set(value) if bar.winfo_exists() else None)
            def work():
                try:
                    path = self.client.download(release, progress, self.cancel.is_set)
                    self.dispatch(lambda:ready(path))
                except Exception as exc:
                    error = str(exc)
                    self.dispatch(lambda:status.configure(text=error) if status.winfo_exists() else None)
                finally:
                    self.busy = False
                    self.dispatch(lambda:button.configure(state='normal') if button.winfo_exists() else None)
            threading.Thread(target=work, daemon=True, name='update-download').start()
        def ready(path):
            if not w.winfo_exists():return
            status.configure(text='Download verified. Ready to install.')
            button.configure(text='Install and close Veyora', command=lambda:self.install(path, release))
        button = ctk.CTkButton(w, text='Download update', command=download)
        button.pack(pady=10)
        def close():
            self.cancel.set()
            w.destroy()
        w.protocol('WM_DELETE_WINDOW', close)
        ctk.CTkButton(w, text='Cancel / Later', command=close).pack(pady=(0,15))

    def install(self, path, release):
        if not getattr(sys, 'frozen', False) or os.name != 'nt':
            messagebox.showinfo('Updates','Installation is supported in the packaged Windows application only.')
            return
        active = [t for t in self.app.queue_manager.get_tasks_by_status() if t['status'] not in self.app.queue_manager.TERMINAL]
        if active or getattr(self.app, '_local_running', False):
            messagebox.showinfo('Updates','Finish or cancel active downloads and translation before installing.')
            return
        if not messagebox.askyesno('Install update','Close Veyora and install the verified update? Your data will be preserved.'):
            return
        from .core import verify_manifest, verify_file
        m=verify_manifest(release['raw'],release['signature'],self.client.keys,release['tag'])
        verify_file(path,m)
        import uuid
        backup=self.directory/'backups'/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
        backup.mkdir(parents=True,exist_ok=True)
        for name in ('settings.json','history.json','config.json'):
            source=self.directory/name
            if source.exists():shutil.copy2(source,backup/name)
        subprocess.Popen([sys.executable,'--install-update',str(os.getpid()),str(path),release['tag']],shell=False)
        self.app._on_close()
