"""Real playlist metadata/selection page using the existing download queue."""
import copy
import threading
import customtkinter as ctk
from ui_controls import OptionMenu


def build_playlist_page(app):
    from main import DownloadEngine, normalize_url
    from runtime_support import friendly_error
    state = app._playlist_state = dict(entries=[], selected=set(), busy=False, enqueueing=False)
    frame = ctk.CTkFrame(app.content_frame, fg_color='transparent')
    frame.grid(row=0, column=0, sticky='nsew', padx=18, pady=14)
    frame.grid_columnconfigure(0, weight=1)
    frame.grid_rowconfigure(6, weight=1)
    app.section_title(frame, 'قائمة التشغيل', 'Playlist', size=24).grid(row=0, column=0, sticky='w', pady=12)
    url = ctk.StringVar()
    entry = ctk.CTkEntry(frame, textvariable=url, height=42, fg_color=app.c['panel2'], border_color=app.c['edge'], text_color=app.c['text'])
    entry.grid(row=1, column=0, sticky='ew', pady=8)
    toolbar = ctk.CTkFrame(frame, fg_color='transparent')
    toolbar.grid(row=2, column=0, sticky='ew')
    status = ctk.CTkLabel(frame, text=app.t('أدخل رابط قائمة تشغيل ثم اختر المقاطع.', 'Load a playlist link, then select videos.'), anchor='w')
    status.grid(row=3, column=0, sticky='ew', pady=8)
    rows = ctk.CTkScrollableFrame(frame, fg_color=app.c['panel'])
    rows.grid(row=6, column=0, sticky='nsew')
    rows.grid_columnconfigure(0, weight=1)
    from playlist_options import QUALITIES,playlist_settings
    saved=getattr(app,'_playlist_preferences',dict(quality='best',container='MP4',subtitles=False,source='auto',target='en',mode='separate'))
    controls=ctk.CTkFrame(frame,fg_color='transparent');controls.grid(row=4,column=0,sticky='ew',pady=8)
    preference={key:ctk.BooleanVar(value=value) if key=='subtitles' else ctk.StringVar(value=value) for key,value in saved.items()}
    quality_labels={'best':app.t('أفضل جودة متاحة','Best Available'),'2160':'4K','1080':'1080p','720':'720p','480':'480p'}
    selections=[('quality',quality_labels,('جودة الفيديو','Video quality')),('container',{'MP4':'MP4','MKV':'MKV'},('الصيغة','Container')),
        ('source',{key:app._label_for_lang(key) for key in ('auto','ar','en','tr','ko')},('لغة المصدر','Source language')),
        ('target',{key:app._label_for_lang(key,False) for key in ('ar','en','tr','ko')},('لغة الترجمة','Subtitle language')),
        ('mode',{'separate':app.t('ملف منفصل','Separate SRT'),'embed':app.t('مسار مدمج','Embedded track'),'burn':app.t('حرق داخل الفيديو','Burn into video')},('نوع الترجمة','Subtitle output'))]
    option_menus={}
    for column,(key,mapping,title) in enumerate(selections):
        controls.grid_columnconfigure(column,weight=1)
        ctk.CTkLabel(controls,text=app.t(*title)).grid(row=0,column=column,sticky='ew',padx=3)
        shown=ctk.StringVar(value=mapping[preference[key].get()]);reverse={v:k for k,v in mapping.items()}
        menu=OptionMenu(controls,variable=shown,values=list(mapping.values()),width=125,command=lambda value,var=preference[key],lookup=reverse:var.set(lookup[value]))
        menu.grid(row=1,column=column,sticky='ew',padx=3);option_menus[key]=menu
    enabled=ctk.CTkCheckBox(controls,text=app.t('تفعيل الترجمة','Enable subtitles'),variable=preference['subtitles'])
    enabled.grid(row=2,column=0,columnspan=2,sticky='w',pady=8)
    hint=ctk.CTkLabel(frame,text=app.t('إن لم تتوفر الدقة المحددة تُستخدم دقة أدنى، ولن تُفرض دقة أعلى.','Unavailable exact resolution falls back to a lower resolution, never a higher one.'),wraplength=850,anchor=app._anchor())
    hint.grid(row=5,column=0,sticky='ew')
    def save_preferences(*_):
        app._playlist_preferences={key:var.get() for key,var in preference.items()}
        for key in ('source','target','mode'):option_menus[key].configure(state='normal' if preference['subtitles'].get() else 'disabled')
    for var in preference.values():var.trace_add('write',save_preferences)
    save_preferences()
    page = [0]
    generation = [0]
    all_var = ctk.BooleanVar(value=True)

    def draw():
        generation[0] += 1
        token = generation[0]
        for child in rows.winfo_children():
            child.destroy()
        start = page[0] * 50
        entries = state['entries'][start:start+50]
        status.configure(text=f"{state.get('title', '')}  •  {len(state['entries'])}  •  {page[0]+1}/{max(1, (len(state['entries'])+49)//50)}")
        def batch(offset=0):
            if token != generation[0] or not rows.winfo_exists():
                return
            for i, item in enumerate(entries[offset:offset+10], start+offset):
                selected = ctk.BooleanVar(value=i in state['selected'])
                def choose(index=i, variable=selected):
                    state['selected'].add(index) if variable.get() else state['selected'].discard(index)
                cb = ctk.CTkCheckBox(rows, text=app.t(str(item['title']), str(item['title'])),
                                    variable=selected, command=choose, font=('Segoe UI', 12))
                cb.grid(row=i-start, column=0, sticky='w', padx=12, pady=6)
            if offset+10 < len(entries):
                app._ui_callbacks.put(lambda: batch(offset+10))
        batch()

    def accept(info, requested_url=None):
        if not frame.winfo_exists():
            return
        state['busy'] = False
        load.configure(state='normal')
        if not info or info.get('error'):
            status.configure(text=str((info or {}).get('error') or 'No playlist data returned'))
            return
        if info.get('type') != 'playlist':
            status.configure(text=app.t('الرابط ليس قائمة تشغيل قابلة للقراءة.', 'This link did not return a readable playlist.'))
            return
        state.update(entries=list(info['entries']), title=info.get('title', ''), selected=set(range(len(info['entries']))))
        all_var.set(True)
        if requested_url:
            url.set(requested_url)
        page[0] = 0
        draw()

    def fetch():
        if state['busy'] or state['enqueueing']:
            return
        try:
            requested_url = normalize_url(url.get())
        except ValueError as exc:
            status.configure(text=str(exc))
            return
        cookies = app.settings.get('cookies_file', '')
        state['busy'] = True
        load.configure(state='disabled')
        status.configure(text=app.t('جارٍ قراءة قائمة التشغيل…', 'Loading playlist…'))
        def work():
            try:
                info = DownloadEngine.fetch_metadata(requested_url, cookies, playlist=True)
            except Exception as exc:
                info = {'error': friendly_error(exc)}
            app._ui_callbacks.put(lambda: accept(info, requested_url))
        threading.Thread(target=work, daemon=True, name='playlist-metadata').start()

    def toggle_all():
        state['selected'] = set(range(len(state['entries']))) if all_var.get() else set()
        draw()

    def download():
        if state['busy'] or state['enqueueing'] or not state['selected']:
            return
        state['enqueueing'] = True
        selected = [state['entries'][i] for i in sorted(state['selected']) if state['entries'][i].get('url')]
        if not selected:
            state['enqueueing'] = False
            status.configure(text=app.t('لا توجد روابط قابلة للتنزيل.', 'No downloadable media links.'))
            return
        settings=playlist_settings(app.settings,**{key:var.get() for key,var in preference.items()})
        folder=app.selected_folder
        enqueue.configure(state='disabled')
        def rejected():
            state['enqueueing']=False
            if enqueue.winfo_exists():enqueue.configure(state='normal')
        def accepted():
            def batch(offset=0):
                for item in selected[offset:offset+5]:
                    app.queue_manager.add_task(item['url'],settings,title=item['title'],selected_folder=folder,video_id=item.get('id',''),thumbnail=item.get('thumbnail',''))
                if offset+5<len(selected):app._ui_callbacks.put(lambda:batch(offset+5))
                else:
                    rejected();state['selected'].clear();app.show_tab('Downloads')
            batch()
        from confirmation import confirm
        options={key:var.get() for key,var in preference.items()}
        ar=f"عدد المقاطع: {len(selected)}\nالجودة: {dict(best='أفضل جودة متاحة').get(options['quality'],QUALITIES[options['quality']])}\nالصيغة: {options['container']}\nالترجمة: {'مفعّلة' if options['subtitles'] else 'متوقفة'}\nاللغة: {options['target']}\nنوع الترجمة: {options['mode']}\nمجلد الحفظ: {folder}"
        en=f"Videos: {len(selected)}\nQuality: {QUALITIES[options['quality']]}\nContainer: {options['container']}\nSubtitles: {options['subtitles']} / {options['target']} / {options['mode']}\nOutput folder: {folder}"
        confirm(app,'مراجعة تنزيل قائمة التشغيل','Review playlist download',ar,en,accepted,rejected)

    load = app.button(toolbar, app.t('قراءة القائمة', 'Load playlist'), fetch, width=160)
    load.pack(side='left', padx=4)
    select = ctk.CTkCheckBox(toolbar, text=app.t('تحديد الكل', 'Select all'), variable=all_var, command=toggle_all)
    select.pack(side='left', padx=12)
    enqueue = app.button(toolbar, app.t('تحميل المحدد', 'Download selected'), download, width=160)
    enqueue.pack(side='left', padx=4)
    def turn(delta):
        page[0] = max(0, min(max(0, (len(state['entries'])-1)//50), page[0]+delta))
        draw()
    app.ghost_button(toolbar, '◀', lambda: turn(-1), width=36).pack(side='left', padx=4)
    app.ghost_button(toolbar, '▶', lambda: turn(1), width=36).pack(side='left', padx=4)
    app._playlist_accept = accept
    app._playlist_controls = dict(url=url, load=load, download=enqueue, status=status, preferences=preference, menus=option_menus, subtitles=enabled)
