"""Bounded page cache with scoped aliases for the existing desktop builders."""
import tkinter as tk
import customtkinter as ctk


CACHE_KEYS = ('card_widgets', '_card_buttons', '_card_snapshots', '_card_progress_bars',
              '_card_info_labels', '_card_title_labels', '_card_percent_labels', '_card_status_labels')


def is_view_binding(value, depth=0):
    if isinstance(value, (tk.Misc, tk.Variable, ctk.CTkImage)):
        return True
    if depth < 3 and isinstance(value, dict):
        return any(is_view_binding(v, depth+1) for v in value.values())
    if depth < 3 and isinstance(value, (list, tuple)):
        return any(is_view_binding(v, depth+1) for v in value)
    return False


class PageController:
    def __init__(self, app):
        self.app = app
        self.pages = {}
        self.active = None
        self.build_counts = {}
        self.switching = False

    def show(self, name, builder):
        app = self.app
        if self.active == name or self.switching:
            return False
        self.switching = True
        parent = app.content_frame
        try:
            if self.active is not None:
                previous = self.pages[self.active]
                previous['host'].grid_remove()
                # Save aliases whose dictionary has been replaced since mounting.
                for key in previous['bindings']:
                    previous['bindings'][key] = getattr(app, key)
                app._pause_local_views()
            if name not in self.pages:
                host = ctk.CTkFrame(parent, fg_color='transparent')
                host.grid_columnconfigure(0, weight=1)
                host.grid_rowconfigure(0, weight=1)
                before = dict(vars(app))
                for key in CACHE_KEYS:
                    setattr(app, key, {})
                if hasattr(app, '_empty_download_label'):
                    delattr(app, '_empty_download_label')
                app.content_frame = host
                try:
                    builder()
                except BaseException:
                    host.destroy()
                    if self.active in self.pages:
                        previous = self.pages[self.active]
                        for key, value in previous['bindings'].items():
                            setattr(app, key, value)
                        previous['host'].grid(row=0, column=0, sticky='nsew')
                    raise
                finally:
                    app.content_frame = parent
                bindings = {key: value for key, value in vars(app).items()
                            if key != 'content_frame' and before.get(key) is not value and is_view_binding(value)}
                bindings.update({key: getattr(app, key) for key in CACHE_KEYS})
                self.pages[name] = dict(host=host, bindings=bindings)
                self.build_counts[name] = self.build_counts.get(name, 0) + 1
            view = self.pages[name]
            for key, value in view['bindings'].items():
                setattr(app, key, value)
            view['host'].grid(row=0, column=0, sticky='nsew')
            self.active = app.active_tab = name
            return True
        finally:
            app.content_frame = parent
            self.switching = False

    def clear(self):
        for page in self.pages.values():
            page['host'].destroy()
        self.pages.clear()
        self.active = None
