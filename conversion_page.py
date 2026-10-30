"""Labeled conversion/audio extraction views backed by the existing task manager."""
from pathlib import Path
from tkinter import filedialog
import customtkinter as ctk
from ui_controls import OptionMenu
from output_actions import launch_output


def build_conversion_page(app):
    kind='Convert';form=app.local_tasks.form(kind)
    frame=ctk.CTkScrollableFrame(app.content_frame,fg_color='transparent')
    frame.grid(row=0,column=0,sticky='nsew',padx=18,pady=14);frame.grid_columnconfigure(0,weight=1)
    card=app.card(frame);card.grid(row=0,column=0,sticky='ew');card.grid_columnconfigure(0,weight=1)
    app.section_title(card,'التحويل والصيغ','Convert & Formats',size=24).grid(row=0,column=0,padx=22,pady=(18,8),sticky='ew')
    path=ctk.StringVar(value=form.get('path',''))
    entry=ctk.CTkEntry(card,textvariable=path,height=40);entry.grid(row=1,column=0,padx=22,pady=6,sticky='ew')
    def choose():
        value=filedialog.askopenfilename(parent=app,filetypes=[('Media','*.mp4 *.mkv *.mov *.webm *.avi *.mp3 *.wav *.m4a'),('All','*.*')])
        if value:path.set(value)
    choose_button=app.ghost_button(card,app.t('اختيار ملف','Choose media'),choose,width=160)
    choose_button.grid(row=2,column=0,pady=6)
    options=ctk.CTkFrame(card,fg_color='transparent');options.grid(row=3,column=0,padx=22,pady=10,sticky='ew')
    for i in range(4):options.grid_columnconfigure(i,weight=1)
    mode=ctk.StringVar(value=form.get('mode','MP4'))
    codec=ctk.StringVar(value=form.get('codec','h264'))
    resolution=ctk.StringVar(value=form.get('resolution','original'))
    quality=ctk.StringVar(value=form.get('quality','auto'))
    bitrate=ctk.StringVar(value=form.get('bitrate','2500k') if form.get('bitrate','2500k')!='auto' else '2500k')
    audio_bitrate=ctk.StringVar(value=form.get('audio_bitrate','192k'))
    maps=[{'MP4':'MP4','MKV':'MKV','MP3':'MP3','WAV':'WAV'}, {'h264':'H.264','h265':'H.265'},
          {'original':app.t('الأصلية','Original'),'1080':'1080p','720':'720p','480':'480p','2160':'2160p'},
          {'auto':app.t('تلقائية','Automatic'),'high':app.t('عالية','High'),'medium':app.t('متوسطة','Medium'),'custom':app.t('مخصصة','Custom bitrate')}]
    internal=[mode,codec,resolution,quality];display=[];menus=[]
    titles=[('صيغة الإخراج','Output format'),('ترميز الفيديو','Video codec'),('دقة الفيديو','Video resolution'),('جودة الإخراج','Output quality')]
    for column,(var,mapping,title) in enumerate(zip(internal,maps,titles)):
        ctk.CTkLabel(options,text=app.t(*title),anchor=app._anchor()).grid(row=0,column=column,padx=5,sticky='ew')
        shown=ctk.StringVar(value=mapping.get(var.get(),next(iter(mapping.values()))));display.append(shown)
        reverse={value:key for key,value in mapping.items()}
        def selected(value,target=var,lookup=reverse):target.set(lookup[value])
        menu=OptionMenu(options,variable=shown,values=list(mapping.values()),command=selected,width=160)
        menu.grid(row=1,column=column,padx=5,pady=4,sticky='ew');menus.append(menu)
        # Programmatic/QA changes to canonical values update labels too.
        var.trace_add('write',lambda *_,variable=var,label=shown,choices=mapping:label.set(choices.get(variable.get(),variable.get())))
    custom=ctk.CTkFrame(card,fg_color='transparent');custom.grid(row=4,column=0,padx=22,sticky='ew')
    ctk.CTkLabel(custom,text=app.t('معدل الفيديو المخصص','Custom video bitrate')).pack(side='left',padx=5)
    custom_menu=OptionMenu(custom,variable=bitrate,values=['1000k','2500k','5000k','10000k'],width=140);custom_menu.pack(side='left')
    audio=ctk.CTkFrame(card,fg_color=app.c['panel2']);audio.grid(row=5,column=0,padx=22,pady=10,sticky='ew')
    ctk.CTkLabel(audio,text=app.t('استخراج الصوت من الفيديو','Extract audio from video'),font=('Segoe UI',14,'bold')).pack(side='left',padx=12,pady=10)
    audio_mode=ctk.StringVar(value='MP3')
    audio_menu=OptionMenu(audio,variable=audio_mode,values=['MP3','WAV'],width=100);audio_menu.pack(side='left',padx=6)
    ctk.CTkLabel(audio,text=app.t('جودة MP3','MP3 bitrate')).pack(side='left',padx=6)
    audio_quality=OptionMenu(audio,variable=audio_bitrate,values=['128k','192k','256k','320k'],width=110);audio_quality.pack(side='left',padx=6)
    status=ctk.CTkLabel(card,text=app.t('اختر الملف والإعدادات ثم ابدأ.','Choose media and options, then start.'),wraplength=760,anchor=app._anchor())
    status.grid(row=6,column=0,padx=22,pady=6,sticky='ew')
    bar=ctk.CTkProgressBar(card);bar.grid(row=7,column=0,padx=22,pady=8,sticky='ew');bar.set(0)
    buttons=ctk.CTkFrame(card,fg_color='transparent');buttons.grid(row=8,column=0,pady=10)
    output=ctk.CTkFrame(card,fg_color='transparent');output.grid(row=9,column=0,pady=(0,14))
    def save(*_):
        app.local_tasks.save_form(kind,path=path.get(),mode=mode.get(),codec=codec.get(),resolution=resolution.get(),quality=quality.get(),bitrate=bitrate.get(),audio_bitrate=audio_bitrate.get())
    for var in (path,*internal,bitrate,audio_bitrate):var.trace_add('write',save)
    def start(audio_only=False):
        if app.local_tasks.busy:
            status.configure(text=app.t('توجد مهمة معالجة نشطة. انتظر اكتمالها أو ألغها من صفحتها.','Another media task is active. Wait for it or cancel it on its page.'));return
        if not path.get().strip():
            status.configure(text=app.t('اختر ملف وسائط أولًا.','Choose a media file first.'));return
        if audio_only:mode.set(audio_mode.get())
        save()
        app.local_tasks.start(kind,Path(path.get().strip().strip('"')),app.selected_folder,'auto','ar',mode.get(),options=dict(codec=codec.get(),resolution=resolution.get(),quality=quality.get(),bitrate=bitrate.get() if quality.get()=='custom' else 'auto',audio_bitrate=audio_bitrate.get()))
        render(True)
    start_button=app.button(buttons,app.t('بدء المعالجة','Start processing'),start,width=180);start_button.pack(side='left',padx=6)
    extract=app.button(audio,app.t('بدء استخراج الصوت','Start audio extraction'),lambda:start(True),width=170);extract.pack(side='right',padx=8)
    cancel=app.ghost_button(buttons,app.t('إلغاء','Cancel'),lambda:(app.local_tasks.cancel(kind),render(True)),width=100);cancel.pack(side='left')
    def open_result(folder=False):
        task=app.local_tasks.snapshot(kind)
        if task and task.status=='completed':launch_output(app,next(iter(task.result.values())),folder)
    play=app.ghost_button(output,app.t('تشغيل الملف الناتج','Play output'),open_result,width=160);play.pack(side='left',padx=6)
    location=app.ghost_button(output,app.t('فتح موقع الملف','Open output folder'),lambda:open_result(True),width=160);location.pack(side='left',padx=6)
    previous=[None];animated=[False]
    def pause():
        bar.stop();animated[0]=False;previous[0]=None
    def render(force=False):
        task=app.local_tasks.snapshot(kind);active=app.local_tasks.snapshot();busy=app.local_tasks.busy
        own=task and task.status in ('running','cancelling')
        key=(task.id if task else None,task.revision if task else 0,int(task.elapsed) if task else 0,busy,mode.get(),quality.get())
        if not force and key==previous[0]:return
        previous[0]=key
        for widget in (entry,choose_button,*menus,audio_menu,extract,audio_quality,start_button):widget.configure(state='disabled' if busy else 'normal')
        for widget in menus[1:]:widget.configure(state='disabled' if busy or mode.get() in ('MP3','WAV') else 'normal')
        custom_menu.configure(state='normal' if not busy and mode.get() in ('MP4','MKV') and quality.get()=='custom' else 'disabled')
        audio_quality.configure(state='normal' if not busy and audio_mode.get()=='MP3' else 'disabled')
        cancel.configure(state='normal' if own and task.status=='running' else 'disabled')
        for button in (play,location):button.configure(state='normal' if task and task.status=='completed' else 'disabled')
        if busy and not own:
            status.configure(text=app.t('توجد مهمة ترجمة نشطة. انتظرها أو ألغها من صفحة الترجمة.','A translation task is active. Wait or cancel it on Translation.'));return
        if task:
            from ui_text import stage_text
            from runtime_support import friendly_error
            text=friendly_error(RuntimeError(task.error),app.is_arabic,record=False) if task.status=='failed' else stage_text(task.stage,app.is_arabic)
            if task.status=='completed':text=app.t('اكتملت المعالجة وحُفظ الملف الناتج.','Processing completed; output saved.')
            status.configure(text=text+'  '+(f'{task.fraction*100:.1f}%  ' if task.fraction is not None else '')+f'{int(task.elapsed)//60:02}:{int(task.elapsed)%60:02}')
            if own and task.fraction is None:
                if not animated[0]:bar.configure(mode='indeterminate');bar.start();animated[0]=True
            else:bar.stop();animated[0]=False;bar.configure(mode='determinate');bar.set(task.fraction or 0)
    for var in (mode,quality,audio_mode):var.trace_add('write',lambda *_:render(True))
    app._local_task_controls=dict(path=path,source=ctk.StringVar(value='auto'),target=ctk.StringVar(value='ar'),mode=mode,start=start_button,cancel=cancel,status=status,progress=bar,extract=extract,audio_mode=audio_mode,play=play,location=location,options=dict(codec=codec,resolution=resolution,quality=quality,bitrate=bitrate))
    app._local_views[kind]=dict(render=render,pause=pause)
    render(True)
