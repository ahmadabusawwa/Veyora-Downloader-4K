"""Cached history view: async file reading and bounded rows per page."""
from pathlib import Path
import threading
import customtkinter as ctk


def build_history_page(app):
    import main
    frame = ctk.CTkFrame(app.content_frame, fg_color='transparent')
    frame.grid(row=0, column=0, sticky='nsew', padx=18, pady=14)
    frame.grid_columnconfigure(0, weight=1)
    frame.grid_rowconfigure(1, weight=1)
    app.section_title(frame, '◷  سجل التنزيلات', 'Download history', size=24).grid(row=0, column=0, sticky='w', pady=12)
    rows = ctk.CTkScrollableFrame(frame, fg_color=app.c['panel'])
    rows.grid(row=1, column=0, sticky='nsew')
    rows.grid_columnconfigure(0, weight=1)
    controls = ctk.CTkFrame(frame, fg_color='transparent')
    controls.grid(row=2, column=0, pady=8)
    caption = ctk.CTkLabel(controls, text='')
    caption.pack(side='left', padx=8)
    state = dict(items=[], page=0, generation=0, busy=False, signature=None)

    def draw():
        state['generation'] += 1
        generation = state['generation']
        for child in rows.winfo_children():
            child.destroy()
        start = state['page']*50
        items = state['items'][start:start+50]
        caption.configure(text=f"{state['page']+1}/{max(1, (len(state['items'])+49)//50)}")
        if not items:
            ctk.CTkLabel(rows, text=app.t('لا يوجد سجل تنزيلات بعد.', 'No download history yet.')).grid(row=0, column=0, pady=40)
        def batch(offset=0):
            if generation != state['generation'] or not rows.winfo_exists():
                return
            for index, item in enumerate(items[offset:offset+10], offset):
                row = ctk.CTkFrame(rows, fg_color=app.c['bg_soft'], corner_radius=10)
                row.grid(row=index, column=0, sticky='ew', padx=8, pady=4)
                row.grid_columnconfigure(0, weight=1)
                ctk.CTkLabel(row, text=main.fix_arabic_text(str(item.get('title', 'Unknown'))),
                    anchor='w', wraplength=620, font=('Segoe UI', 13, 'bold')).grid(row=0, column=0, sticky='ew', padx=14, pady=8)
                ctk.CTkLabel(row, text=str(item.get('time', ''))+'  •  '+str(item.get('platform', ''))+'  •  '+app.t('مكتمل', 'Completed'),
                    text_color=app.c['muted'], anchor='w').grid(row=1, column=0, sticky='ew', padx=14)
                if item.get('_available_file'):
                    app.ghost_button(row, app.t('إظهار الملف', 'Show in folder'),
                        lambda path=item['file_path']: main.open_file_in_explorer(path), width=118, height=28).grid(row=2, column=0, sticky='w', padx=14, pady=8)
            if offset+10 < len(items):
                app._ui_callbacks.put(lambda: batch(offset+10))
        batch()

    def refresh():
        try:
            signature = main.HISTORY_FILE.stat().st_mtime_ns
        except OSError:
            signature = 0
        if state['busy'] or signature == state['signature']:
            return
        state['busy'] = True
        def apply(items):
            if not frame.winfo_exists():
                return
            state.update(items=items, signature=signature, busy=False)
            state['page'] = min(state['page'], max(0, (len(items)-1)//50))
            draw()
        def work():
            items = main.HistoryManager.load()
            for item in items:
                item['_available_file'] = bool(item.get('file_path') and Path(item['file_path']).is_file())
            app._ui_callbacks.put(lambda: apply(items))
        threading.Thread(target=work, daemon=True, name='history-reader').start()

    def turn(delta):
        state['page'] = max(0, min(max(0, (len(state['items'])-1)//50), state['page']+delta))
        draw()
    app.ghost_button(controls, '◀', lambda: turn(-1), width=36).pack(side='left', padx=4)
    app.ghost_button(controls, '▶', lambda: turn(1), width=36).pack(side='left', padx=4)
    app._history_refresh = refresh
    refresh()
