"""Native CustomTkinter desktop shell; reuses the 1.7 queue and media engine."""
import queue
import threading
import io
from pathlib import Path
import customtkinter as ctk
from PIL import Image
from tkinter import filedialog, messagebox
from ui_icons import icon
from main import (VeyoraApp, APP_VERSION, CONFIG_DIR, SettingsManager, DownloadEngine,
                  SUBTITLE_CHOICES, TRANSLATION_DIRECTIONS, LANGUAGES, fix_arabic_text,
                  is_valid_url, normalize_url, open_folder_in_explorer)

BG='#090f15'; PANEL='#101e28'; EDGE='#284152'; BLUE='#0088ff'; MUTED='#a8bdd0'

class DesktopApp(VeyoraApp):
    def __init__(self):
        self.icons={name:icon(name) for name in ('download','home','audio','list','translate','folder','convert','settings','clock','help')}
        self._local_cancel=threading.Event()
        self._local_running=False
        super().__init__()
        self.title('Veyora Pro 2.0 — Downloader & Translator')
        self.geometry('1536x980')
        self.minsize(1080,760)
        self.configure(fg_color=BG)

    def t(self, ar, en):
        return fix_arabic_text(ar) if self.settings.get('ui_language','ar')=='ar' else en

    def button(self, parent, text, command, **kw):
        symbols={'⇩':'download','⌂':'home','♫':'audio','☷':'list','▣':'translate','▱':'folder','⇄':'convert','⚙':'settings','◷':'clock','?':'help'}
        for symbol,name in symbols.items():
            if symbol in text:
                text=text.replace(symbol,'').strip();kw['image']=self.icons[name];break
        return ctk.CTkButton(parent,text=text,command=command,fg_color=kw.pop('fg_color',BLUE),hover_color='#164d78',corner_radius=10,height=40,**kw)

    def setup_sidebar(self):
        self.grid_rowconfigure(0,weight=0)
        self.grid_rowconfigure(1,weight=1)
        self.top=ctk.CTkFrame(self,fg_color=BG,corner_radius=0,height=82)
        self.top.grid(row=0,column=0,columnspan=2,sticky='ew')
        self.top.grid_columnconfigure(5,weight=1)
        logo=Image.open(Path(__file__).with_name('logo.png'))
        self.brand=ctk.CTkImage(logo,size=(54,54))
        ctk.CTkLabel(self.top,text='',image=self.brand).grid(row=0,column=0,padx=(16,8),pady=12)
        ctk.CTkLabel(self.top,text='Veyora Pro  4K\nDownloader & Translator',font=('Segoe UI',18,'bold'),anchor='w').grid(row=0,column=1,padx=(0,24))
        for i,(ar,en,name) in enumerate([('⌂  الرئيسية','Home','Dashboard'),('⇩  التنزيلات','Downloads','Downloads'),('▣  الترجمة','Translation','Translation'),('⚙  الإعدادات','Settings','Settings')],2):
            self.button(self.top,self.t(ar,en),lambda n=name:self.show_tab(n),width=120,fg_color=PANEL).grid(row=0,column=i,padx=6)
        self.button(self.top,'v'+APP_VERSION+'  •  '+self.t('فحص التحديثات','Check updates'),lambda:self.updater.check(True),width=200).grid(row=0,column=6,padx=16)
        self.sidebar=ctk.CTkFrame(self,width=230,fg_color=BG,corner_radius=0)
        self.sidebar.grid(row=1,column=0,sticky='nsw')
        self.sidebar.grid_columnconfigure(0,weight=1)
        self.sidebar.grid_rowconfigure(9,weight=1)
        links=[('⇩  تحميل فيديو','Video download',lambda:self.home_mode(False)),('♫  تحميل الصوت','Audio download',lambda:self.home_mode(True)),('☷  قائمة التشغيل','Playlists',lambda:self.home_mode(False)),('▣  الترجمة','Translation',lambda:self.show_tab('Translation')),('⇄  التحويل والصيغ','Convert / formats',lambda:self.show_tab('Convert')),('▱  الملفات','Files',lambda:self.open_selected_folder()),('⚙  الإعدادات','Settings',lambda:self.show_tab('Settings')),('◷  السجل','History',lambda:self.show_tab('History')),('?  الدعم','Supported sites',lambda:self.show_supported_sites())]
        for i,(ar,en,command) in enumerate(links):
            self.button(self.sidebar,self.t(ar,en),command,fg_color='#143957' if i==0 else 'transparent',anchor='w',width=210).grid(row=i,column=0,padx=12,pady=8,sticky='ew')
        ctk.CTkLabel(self.sidebar,text=self.t('♛\nVeyora Pro\nمجاني دائمًا','♛\nVeyora Pro\nAlways free'),text_color='#ffca45',font=('Segoe UI',19,'bold'),fg_color='#161b1e',corner_radius=14,width=180,height=140).grid(row=10,column=0,padx=24,pady=18)
        self.button(self.sidebar,'العربية / English',self.toggle_language,fg_color=PANEL).grid(row=11,column=0,padx=15,pady=10)

    def setup_main_content(self):
        self.content_frame=ctk.CTkFrame(self,fg_color='#0b151d',border_width=1,border_color=EDGE,corner_radius=18)
        self.content_frame.grid(row=1,column=1,sticky='nsew',padx=(0,14),pady=(4,12))
        self.content_frame.grid_columnconfigure(0,weight=1)
        self.content_frame.grid_rowconfigure(0,weight=1)

    def toggle_language(self):
        self.settings['ui_language']='en' if self.settings.get('ui_language','ar')=='ar' else 'ar'
        SettingsManager.save(self.settings)
        self.top.destroy();self.sidebar.destroy();self.setup_sidebar();self.show_tab('Dashboard')

    def home_mode(self,audio):
        self.show_tab('Dashboard')
        self.mode_var.set('Audio (Extract)' if audio else 'Video')
        self.on_mode_change()

    def show_tab(self,name):
        if name in ('Translation','Convert'):
            self.active_tab=name
            for w in self.content_frame.winfo_children():w.destroy()
            for cache in (self.card_widgets,self._card_buttons,self._card_snapshots,self._card_progress_bars,self._card_info_labels,self._card_title_labels):cache.clear()
            self.build_local_tab(convert=name=='Convert')
        else:
            super().show_tab(name)

    def panel(self,parent,title,col):
        p=ctk.CTkFrame(parent,fg_color=PANEL,border_width=1,border_color=EDGE,corner_radius=14)
        p.grid(row=0,column=col,sticky='nsew',padx=6)
        p.grid_columnconfigure(0,weight=1)
        ctk.CTkLabel(p,text=title,font=('Segoe UI',16,'bold'),anchor='e').grid(row=0,column=0,padx=16,pady=12,sticky='ew')
        return p

    def build_dashboard_tab(self):
        f=ctk.CTkScrollableFrame(self.content_frame,fg_color='transparent')
        f.grid(row=0,column=0,sticky='nsew',padx=12,pady=12)
        f.grid_columnconfigure(0,weight=1);f.grid_rowconfigure(3,weight=1)
        line=ctk.CTkFrame(f,fg_color='transparent');line.grid(row=0,column=0,sticky='ew');line.grid_columnconfigure(0,weight=1)
        self.url_entry=ctk.CTkEntry(line,placeholder_text=self.t('ألصق رابط الفيديو هنا','Paste a video link'),height=54,border_color='#39bcff',fg_color=PANEL,font=('Segoe UI',16))
        self.url_entry.grid(row=0,column=0,sticky='ew',padx=(0,8))
        self.url_entry.bind('<Button-3>',self.show_url_context_menu)
        self.button(line,self.t('لصق','Paste'),self.paste_only,width=78).grid(row=0,column=1,padx=4)
        self.button(line,self.t('تحليل الرابط  ⌕','Analyze link  ⌕'),self.analyze,width=170).grid(row=0,column=2,padx=4)
        preview=ctk.CTkFrame(f,fg_color='transparent');preview.grid(row=1,column=0,sticky='ew',pady=16);preview.grid_columnconfigure(1,weight=1);preview.grid_columnconfigure(2,weight=1)
        self.preview_image=ctk.CTkLabel(preview,text='▶',width=250,height=140,fg_color=PANEL,corner_radius=12,font=('Segoe UI',38),text_color=BLUE)
        self.preview_image.grid(row=0,column=0,rowspan=2,padx=(0,16))
        self.preview_title=ctk.CTkLabel(preview,text=self.t('أضف رابطًا لعرض معلومات الفيديو','Add a link to inspect the video'),font=('Segoe UI',19,'bold'),anchor='w',wraplength=390)
        self.preview_title.grid(row=0,column=1,sticky='ew')
        self.preview_meta=ctk.CTkLabel(preview,text=self.t('التحميل والترجمة • العربية، الإنجليزية، التركية، الكورية','Download & translate • Arabic, English, Turkish, Korean'),text_color=MUTED,anchor='w',wraplength=390)
        self.preview_meta.grid(row=1,column=1,sticky='new')
        self.video_info=ctk.CTkLabel(preview,text=self.t('معلومات الفيديو\n\nبانتظار تحليل رابط حقيقي','Video information\n\nWaiting for a real link'),fg_color=PANEL,corner_radius=12,width=280,height=140,anchor='e',justify='right')
        self.video_info.grid(row=0,column=2,rowspan=2,sticky='ew',padx=(16,0))
        options=ctk.CTkFrame(f,fg_color='transparent');options.grid(row=2,column=0,sticky='ew')
        for i in range(3):options.grid_columnconfigure(i,weight=1,uniform='cards')
        dl=self.panel(options,self.t('⇩  خيارات التحميل','⇩  Download options'),0)
        tr=self.panel(options,self.t('▣  الترجمة','▣  Translation'),1)
        extra=self.panel(options,self.t('⚙  خيارات إضافية','⚙  More options'),2)
        self.mode_var=ctk.StringVar(value='Video');self.quality_var=ctk.StringVar(value=self.settings.get('quality','Best Available (4K/HD)'));self.format_var=ctk.StringVar(value=self.settings.get('format','MP4'))
        def menu(p,row,values,var):
            ctk.CTkOptionMenu(p,values=values,variable=var,fg_color='#142b3b',button_color='#1a3d54',dropdown_fg_color=PANEL,height=34,dynamic_resizing=False).grid(row=row,column=0,sticky='ew',padx=16,pady=6)
        menu(dl,1,['Best Available (4K/HD)','2160p (4K)','1440p (2K)','1080p (Full HD)','720p (HD)','480p'],self.quality_var)
        menu(dl,2,['MP4','MKV','MOV','WEBM'],self.format_var)
        self.folder_path_label=ctk.CTkLabel(dl,text=self.selected_folder,anchor='w',wraplength=290,text_color=MUTED);self.folder_path_label.grid(row=3,column=0,padx=16,pady=6,sticky='ew')
        self.button(dl,self.t('▱  مكان الحفظ','▱  Save location'),self.browse_folder,fg_color='#183448').grid(row=4,column=0,padx=16,pady=6,sticky='ew')
        self.thumb_var=ctk.BooleanVar(value=self.settings.get('save_thumbnail',True))
        ctk.CTkCheckBox(dl,text=self.t('تحميل الصورة المصغرة','Save thumbnail'),variable=self.thumb_var).grid(row=5,column=0,padx=16,pady=8,sticky='w')
        self.sub_var=ctk.BooleanVar(value=self.settings.get('download_subs',True))
        ctk.CTkSwitch(tr,text=self.t('تفعيل الترجمة','Enable subtitles'),variable=self.sub_var).grid(row=1,column=0,padx=16,pady=8,sticky='e')
        display={v:k for k,v in SUBTITLE_CHOICES.items()}
        self.sub_lang_var=ctk.StringVar(value=display.get(self.settings.get('sub_lang','auto-ar'),'Auto-Translate: English -> Arabic'))
        self.source_var=ctk.StringVar(value='auto')
        self.target_var=ctk.StringVar(value='ar')
        language_row=ctk.CTkFrame(tr,fg_color='transparent')
        language_row.grid(row=2,column=0,padx=16,pady=6,sticky='ew')
        language_row.grid_columnconfigure((0,1),weight=1)
        for col,var,values in [(0,self.source_var,['auto','ar','en','tr','ko']),(1,self.target_var,['ar','en','tr','ko'])]:
            ctk.CTkOptionMenu(language_row,values=values,variable=var,width=100,fg_color='#142b3b',button_color='#1a3d54').grid(row=0,column=col,padx=3,sticky='ew')
        ctk.CTkLabel(tr,text=self.t('لغة الفيديو ← الترجمة إلى','Speech language → translate to'),text_color=MUTED).grid(row=3,column=0,pady=3)

        self.dashboard_subtitle_mode=ctk.StringVar(value=self.settings.get('subtitle_mode','separate'))
        menu(tr,4,['separate','embed','burn','both'],self.dashboard_subtitle_mode)
        ctk.CTkLabel(tr,text=self.t('SRT مستقل • MKV مدمج • MP4 محروق','Separate SRT • MKV track • Burned MP4'),text_color=MUTED,wraplength=280).grid(row=5,column=0,padx=16,pady=6)
        self.original_var=ctk.BooleanVar(value=self.settings.get('save_original_subtitles',False))
        ctk.CTkCheckBox(tr,text=self.t('حفظ النص الأصلي أيضًا','Also save original transcript'),variable=self.original_var).grid(row=6,column=0,padx=16,pady=8,sticky='e')
        self.audio_var=ctk.BooleanVar(value=False)
        ctk.CTkSwitch(extra,text=self.t('استخراج الصوت فقط (MP3)','Extract audio only (MP3)'),variable=self.audio_var,command=lambda:self.mode_var.set('Audio (Extract)' if self.audio_var.get() else 'Video')).grid(row=1,column=0,padx=16,pady=8,sticky='w')
        self.audio_format_frame=ctk.CTkFrame(extra,fg_color='transparent')
        self.audio_bitrate_var=ctk.StringVar(value=self.settings.get('audio_bitrate','320 kbps'));self.audio_format_var=ctk.StringVar(value='Best Available')
        menu(extra,2,['320 kbps','256 kbps','192 kbps','128 kbps'],self.audio_bitrate_var)
        self.smart_mode_switch=ctk.CTkSwitch(extra,text=self.t('تحميل بنقرة واحدة','One-click download'),command=self.toggle_smart_mode)
        self.smart_mode_switch.grid(row=3,column=0,padx=16,pady=8,sticky='w')
        if self.smart_mode:self.smart_mode_switch.select()
        self.button(extra,self.t('خيارات التحميل المتقدمة','Advanced download options'),lambda:self.show_advanced(),fg_color='#183448').grid(row=4,column=0,padx=16,pady=6,sticky='ew')
        self.button(extra,self.t('⇩  بدء التحميل والترجمة','⇩  Download & translate'),self.start_download_action).grid(row=5,column=0,padx=16,pady=12,sticky='ew')
        queue_panel=ctk.CTkFrame(f,fg_color=PANEL,border_width=1,border_color=EDGE,corner_radius=14)
        queue_panel.grid(row=3,column=0,sticky='nsew',pady=(14,0));queue_panel.grid_columnconfigure(0,weight=1);queue_panel.grid_rowconfigure(1,weight=1)
        ctk.CTkLabel(queue_panel,text=self.t('⇩  قائمة التنزيلات','⇩  Download queue'),font=('Segoe UI',17,'bold')).grid(row=0,column=0,padx=16,pady=8,sticky='w')
        self.button(queue_panel,self.t('عرض الكل','View all'),lambda:self.show_tab('Downloads'),width=100,fg_color='#183448').grid(row=0,column=1,padx=12)
        self.downloads_scroll=ctk.CTkScrollableFrame(queue_panel,fg_color='transparent',height=190);self.downloads_scroll.grid(row=1,column=0,columnspan=2,sticky='nsew');self.downloads_scroll.grid_columnconfigure(0,weight=1)
        self.status_label=ctk.CTkLabel(queue_panel,text='',text_color=MUTED);self.status_label.grid(row=2,column=0,columnspan=2,pady=4)
        self.render_download_items()
        layout=[None]
        def reflow(event):
            narrow=event.width<1000
            if narrow==layout[0]:return
            layout[0]=narrow
            if narrow:
                extra.grid(row=1,column=0,columnspan=2,pady=8)
                options.grid_columnconfigure(2,weight=0)
            else:
                extra.grid(row=0,column=2,columnspan=1,pady=0)
                options.grid_columnconfigure(2,weight=1)
        options.bind('<Configure>',reflow)

    def show_advanced(self):
        self.show_tab('Dashboard')
        for w in self.content_frame.winfo_children():w.destroy()
        VeyoraApp.build_dashboard_tab(self)
        for name in ('original_var','source_var','target_var'):
            if hasattr(self,name):delattr(self,name)

    def paste_only(self):
        try:
            text=self.clipboard_get();self.url_entry.delete(0,'end');self.url_entry.insert(0,text)
        except Exception:pass

    def start_download_action(self):
        if hasattr(self,'original_var'):
            self.settings['save_original_subtitles']=self.original_var.get()
            self.settings['save_thumbnail']=self.thumb_var.get()
            self.settings['audio_bitrate']=self.audio_bitrate_var.get()
        if hasattr(self, 'source_var'):
            pair=(self.source_var.get(),self.target_var.get())
            if pair[0]==pair[1] and self.sub_var.get():
                messagebox.showerror('Veyora','Choose different source and target languages');return
            for label,key in SUBTITLE_CHOICES.items():
                if TRANSLATION_DIRECTIONS.get(key)==pair:
                    self.sub_lang_var.set(label);break
        super().start_download_action()

    def analyze(self):
        url=self.url_entry.get().strip()
        if getattr(self,'_metadata_busy',False):return
        if not is_valid_url(url):
            messagebox.showerror('Veyora',self.t('أدخل رابط HTTP أو HTTPS صالحًا','Enter a valid HTTP(S) link'));return
        self.preview_title.configure(text=self.t('جارٍ تحليل الرابط…','Analyzing link…'))
        self._metadata_busy=True
        def work():
            try:
                info=DownloadEngine.fetch_metadata(normalize_url(url),self.settings.get('cookies_file',''))
                self._ui_callbacks.put(lambda:self.show_preview(info))
            finally:self._metadata_busy=False
        threading.Thread(target=work,daemon=True,name='metadata-preview').start()

    def show_preview(self,info):
        if self.active_tab!='Dashboard':return
        if info and info.get('error'):
            self.preview_title.configure(text=self.t('تعذر تحليل الرابط','Could not analyze link'))
            self.preview_meta.configure(text=info['error'])
            return
        if not info:
            self.preview_title.configure(text=self.t('تعذر تحليل الرابط','Could not analyze the link'));return
        self.preview_title.configure(text=fix_arabic_text(info.get('title','Video')))
        duration=info.get('duration') or 0
        self.preview_meta.configure(text=f"{info.get('uploader','')}\n{info.get('view_count') or '—'} views • {int(duration)//60}:{int(duration)%60:02}")
        self.video_info.configure(text=self.t('معلومات الفيديو','Video information')+f"\n\n{info.get('platform','')}\n{info.get('resolution','')}\n{info.get('uploader','')}")
        # Thumbnail is intentionally fetched through a bounded background request.
        url=info.get('thumbnail')
        if url and url.startswith('https://'):
            def work():
                try:
                    import requests
                    with requests.get(url,timeout=15,stream=True) as r:
                        r.raise_for_status();buf=bytearray()
                        for chunk in r.iter_content(65536):
                            buf.extend(chunk)
                            if len(buf)>5*1024*1024:raise ValueError('Thumbnail too large')
                    im=Image.open(io.BytesIO(buf));im.thumbnail((500,280));im=im.copy()
                    self._ui_callbacks.put(lambda:self.set_preview_image(im) if self.active_tab=='Dashboard' else None)
                except Exception:pass
            threading.Thread(target=work,daemon=True,name='thumbnail').start()

    def set_preview_image(self,image):
        self.preview_ctk_image=ctk.CTkImage(image,size=(250,140));self.preview_image.configure(image=self.preview_ctk_image,text='')

    def create_download_card(self, task, idx):
        tid=task['id']
        card=ctk.CTkFrame(self.downloads_scroll,fg_color='#0d1922',corner_radius=10,border_width=1,border_color=EDGE)
        card.grid(row=idx,column=0,sticky='ew',padx=6,pady=4)
        card.grid_columnconfigure(1,weight=1)
        card.grid_columnconfigure(2,weight=1)
        badge=task['settings'].get('format','MP4')
        ctk.CTkLabel(card,text='▶\n'+badge,width=82,height=66,fg_color='#163347',corner_radius=8,text_color=MUTED).grid(row=0,column=0,rowspan=2,padx=8,pady=8)
        title=ctk.CTkLabel(card,text='',anchor='w',font=('Segoe UI',14,'bold'),wraplength=250)
        title.grid(row=0,column=1,padx=10,pady=(8,0),sticky='ew')
        info=ctk.CTkLabel(card,text='',anchor='w',text_color=MUTED,wraplength=420)
        info.grid(row=1,column=1,columnspan=2,padx=10,pady=(0,8),sticky='ew')
        bar=ctk.CTkProgressBar(card,progress_color=BLUE,height=10,width=200)
        bar.grid(row=0,column=2,padx=15,pady=12,sticky='ew');bar.set(task['progress'])
        actions=ctk.CTkFrame(card,fg_color='transparent');actions.grid(row=0,column=3,rowspan=2,padx=10,pady=4)
        commands={'pause':('Ⅱ',lambda:self.queue_manager.pause_task(tid)), 'resume':('▶',lambda:self.queue_manager.resume_task(tid)), 'cancel':('×',lambda:self.queue_manager.cancel_task(tid)), 'retry':('↻',lambda:self.queue_manager.retry_task(tid)), 'remove':('×',lambda:self.queue_manager.remove_task(tid)), 'show':('▱',lambda:self._show_task_file(tid))}
        self.card_widgets[tid]=card;self._card_title_labels[tid]=title;self._card_info_labels[tid]=info;self._card_progress_bars[tid]=bar
        self._card_buttons[tid]={key:ctk.CTkButton(actions,text=label,width=42,height=26,fg_color='#1b3344',command=command) for key,(label,command) in commands.items()}

    def _update_download_card(self,task):
        super()._update_download_card(task)
        status=task['status']
        self._card_progress_bars[task['id']].configure(progress_color='#24d582' if status=='Completed' else '#f13d49' if status=='Failed' else BLUE)

    def refresh_ui(self):
        if self.active_tab in ('Dashboard','Downloads') and hasattr(self,'downloads_scroll') and self.downloads_scroll.winfo_exists():self.render_download_items()

    def build_local_tab(self,convert=False):
        f=ctk.CTkFrame(self.content_frame,fg_color=PANEL);f.grid(row=0,column=0,sticky='nsew',padx=20,pady=20);f.grid_columnconfigure(0,weight=1)
        ctk.CTkLabel(f,text=self.t('التحويل والصيغ' if convert else 'ترجمة ملف محلي','Convert media' if convert else 'Translate local media'),font=('Segoe UI',26,'bold')).grid(row=0,column=0,pady=24)
        path=ctk.StringVar();ctk.CTkEntry(f,textvariable=path,height=42).grid(row=1,column=0,padx=24,pady=12,sticky='ew')
        def choose():
            value=filedialog.askopenfilename(filetypes=[('Media / subtitles','*.mp4 *.mkv *.mov *.mp3 *.wav *.srt'),('All files','*.*')])
            if value:path.set(value)
        self.button(f,self.t('اختيار ملف','Choose file'),choose).grid(row=2,column=0,pady=8)
        src=ctk.StringVar(value='auto');dst=ctk.StringVar(value='ar');mode=ctk.StringVar(value='separate')
        for row,var,values in [(3,src,['auto']+list(LANGUAGES)),(4,dst,list(LANGUAGES)),(5,mode,['MP4','MKV','MP3'] if convert else ['separate','embed','burn','both'])]:
            if convert and row<5:continue
            if convert:mode.set('MP4')
            ctk.CTkOptionMenu(f,variable=var,values=values).grid(row=row,column=0,pady=8)
        label=ctk.CTkLabel(f,text=self.t('لغة المصدر • اللغة الهدف • طريقة الحفظ','Source language • target language • output mode'));label.grid(row=6,column=0,pady=10)
        bar=ctk.CTkProgressBar(f);bar.grid(row=7,column=0,padx=24,pady=14,sticky='ew');bar.set(0)
        def progress(stage,fraction=None):
            def render():
                if not label.winfo_exists():return
                label.configure(text=fix_arabic_text(stage));bar.set(fraction or 0)
            self._ui_callbacks.put(render)
        def start():
            if self._local_running:return
            media=Path(path.get())
            if not media.is_file():messagebox.showerror('Veyora','Choose an existing media file');return
            source,target,output=src.get(),dst.get(),mode.get()
            self._local_running=True;self._local_cancel.clear()
            def checkpoint():
                if self._local_cancel.is_set():raise RuntimeError('Cancelled by user')
            def worker():
                try:
                    if convert:
                        from translator.video_renderer import run_ffmpeg
                        import uuid
                        dest=Path(self.selected_folder)/(media.stem+'.'+uuid.uuid4().hex[:8]+'.'+output.lower())
                        args=['-i',str(media)]
                        args+=['-vn','-c:a','libmp3lame'] if output=='MP3' else ['-c:v','libx264','-c:a','aac']
                        run_ffmpeg(args+[str(dest)],checkpoint)
                        result={'video':str(dest)}
                    else:
                        from translator.pipeline import TranslationPipeline
                        result=TranslationPipeline(media,self.selected_folder).run(mode=output,checkpoint=checkpoint,progress=progress,source_lang=source,target_lang=target,save_original=self.settings.get('save_original_subtitles',False))
                    progress('Saved: '+', '.join(result.values()),1)
                except Exception as exc:progress(str(exc),0)
                finally:self._local_running=False
            threading.Thread(target=worker,daemon=True,name='local-media').start()
        self.button(f,self.t('بدء المعالجة','Start processing'),start).grid(row=8,column=0,pady=10)
        self.button(f,self.t('إلغاء','Cancel'),self._local_cancel.set,fg_color='#813448').grid(row=9,column=0,pady=10)

    def _on_close(self):
        self._local_cancel.set()
        super()._on_close()
