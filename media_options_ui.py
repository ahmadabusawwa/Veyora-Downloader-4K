"""Small existing-theme option dialogs; heavy preview rendering stays off Tk."""
import tempfile
import threading
from pathlib import Path
from tkinter import colorchooser
import customtkinter as ctk
from PIL import Image
from translator.subtitle_style import DEFAULT, normalize_style


def subtitle_options(app, path):
    existing = getattr(app, '_subtitle_options_window', None)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        return
    window = app._subtitle_options_window = ctk.CTkToplevel(app)
    window.title(app.t('مظهر الترجمة', 'Subtitle appearance'))
    window.geometry('680x600')
    window.configure(fg_color=app.c['bg'])
    style = {**DEFAULT, **app.settings.get('subtitle_style', {})}
    variables = {}
    for row, (key, ar, en) in enumerate([('size_percent','حجم الخط (% من ارتفاع الفيديو)','Font size (% of video height)'), ('outline','سُمك الحدود (عند 720p)','Outline (at 720p)'), ('margin_percent','الهامش (% من ارتفاع الفيديو)','Vertical margin (% of height)'), ('color','لون الخط #RRGGBB','Font color #RRGGBB'), ('position','الموقع: bottom أو top','Position: bottom or top')]):
        ctk.CTkLabel(window, text=app.t(ar,en)).grid(row=row,column=0,padx=12,pady=5)
        variable = variables[key] = ctk.StringVar(value=str(style[key]))
        ctk.CTkEntry(window,textvariable=variable,width=180).grid(row=row,column=1,padx=12,pady=5)
    def color():
        selected = colorchooser.askcolor(parent=window, initialcolor=variables['color'].get())[1]
        if selected: variables['color'].set(selected)
    app.ghost_button(window,app.t('اختيار لون','Choose color'),color).grid(row=5,column=0)
    status = ctk.CTkLabel(window,text='',wraplength=620)
    status.grid(row=7,column=0,columnspan=2,pady=6)
    preview = ctk.CTkLabel(window,text='')
    preview.grid(row=8,column=0,columnspan=2,pady=8)
    def values():
        return normalize_style({key:value.get() for key,value in variables.items()})
    def save():
        try:
            app.settings['subtitle_style'] = values()
            from main import SettingsManager
            SettingsManager.save(app.settings)
            status.configure(text=app.t('حُفظت الإعدادات.','Settings saved.'))
        except ValueError as exc:
            status.configure(text=str(exc))
    window._save_button = app.button(window,app.t('حفظ','Save'),save)
    window._save_button.grid(row=6,column=0,pady=8)
    window._style_controls = variables
    def start_preview():
        try:
            selected = values()
            media = path.get()
            if not media.strip(): raise ValueError('Choose a video first / اختر فيديو أولًا')
        except ValueError as exc:
            status.configure(text=str(exc)); return
        button.configure(state='disabled')
        status.configure(text=app.t('جارٍ إنشاء المعاينة…','Rendering preview…'))
        def work():
            try:
                from translator.video_renderer import preview_subtitles
                with tempfile.TemporaryDirectory(prefix='veyora-style-') as root:
                    output = Path(root)/'preview.png'
                    preview_subtitles(media,output,selected)
                    with Image.open(output) as img:
                        image = img.copy()
                def done():
                    if not window.winfo_exists(): return
                    image.thumbnail((620,280))
                    window._preview_image = ctk.CTkImage(image,size=image.size)
                    preview.configure(image=window._preview_image)
                    status.configure(text=app.t('معاينة من الفيديو باستخدام إعدادات التصدير.','Actual video frame using export styling.'))
                    button.configure(state='normal')
                app._ui_callbacks.put(done)
            except Exception as exc:
                from runtime_support import friendly_error
                message = friendly_error(exc,app.is_arabic)
                def failed():
                    if window.winfo_exists():
                        status.configure(text=message);button.configure(state='normal')
                app._ui_callbacks.put(failed)
        threading.Thread(target=work,daemon=True,name='subtitle-preview').start()
    button = app.button(window,app.t('معاينة','Preview'),start_preview)
    button.grid(row=6,column=1,pady=8)
    window._preview_button = button
