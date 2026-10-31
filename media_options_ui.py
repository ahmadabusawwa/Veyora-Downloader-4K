"""Debounced live libass preview, one bounded worker, shared export styling."""
import queue
import tempfile
import threading
from pathlib import Path
from tkinter import colorchooser
import customtkinter as ctk
from ui_controls import CodedOptionMenu
from PIL import Image,ImageOps
from translator.subtitle_style import DEFAULT,normalize_style


def subtitle_options(app,path):
    previous=getattr(app,'_subtitle_options_window',None)
    if previous is not None and previous.winfo_exists():previous.lift();return
    window=app._subtitle_options_window=ctk.CTkToplevel(app)
    window.title('محرّر مظهر الترجمة' if app.is_arabic else 'Subtitle appearance editor')
    scale=window._get_window_scaling()
    screen_width=int(window.winfo_screenwidth()/scale);screen_height=int(window.winfo_screenheight()/scale)
    width=min(1080,max(320,screen_width-40));height=min(700,max(320,screen_height-120))
    window.geometry(f'{width}x{height}+{max(0,(screen_width-width)//2)}+{max(0,(screen_height-height-80)//2)}')
    window.minsize(min(860,width),min(580,height));window.configure(fg_color=app.c['bg']);window.transient(app)
    window.grid_columnconfigure(1,weight=1);window.grid_rowconfigure(0,weight=1)
    left=ctk.CTkScrollableFrame(window,width=246,fg_color=app.c['panel']);left.grid(row=0,column=0,sticky='ns',padx=14,pady=14)
    right=ctk.CTkFrame(window,fg_color=app.c['panel2'],border_width=1,border_color=app.c['edge']);right.grid(row=0,column=1,sticky='nsew',padx=(0,14),pady=14)
    right.grid_columnconfigure(0,weight=1);right.grid_rowconfigure(1,weight=1)
    ctk.CTkLabel(right,text=app.t('معاينة حية من الفيديو','Live video preview'),font=('Segoe UI',17,'bold')).grid(row=0,column=0,pady=12)
    preview=ctk.CTkLabel(right,width=1,height=1,text=app.t('جارٍ تجهيز المعاينة…','Preparing preview…'),fg_color='#080d14',corner_radius=8)
    preview.grid(row=1,column=0,sticky='nsew',padx=12,pady=8)
    status=ctk.CTkLabel(right,text='',wraplength=620,anchor=app._anchor());status.grid(row=2,column=0,padx=12,pady=12,sticky='ew')
    try:style=normalize_style(app.settings.get('subtitle_style'))
    except (ValueError,TypeError):style=dict(DEFAULT)
    variables={key:ctk.StringVar(value=str(value)) for key,value in style.items()}
    variable_traces=[]
    sliders=[]
    for row,(key,ar,en,low,high) in enumerate([('size_percent','حجم الخط (% من الارتفاع)','Font size (% of height)',1,10),('outline','سُمك الحد الأسود','Black outline',0,5),('margin_percent','الهامش العمودي (%)','Vertical margin (%)',0,35)]):
        ctk.CTkLabel(left,text=app.t(ar,en),anchor=app._anchor()).grid(row=row*2,column=0,padx=12,pady=(12,2),sticky='ew')
        field=ctk.CTkFrame(left,fg_color='transparent');field.grid(row=row*2+1,column=0,padx=12,sticky='ew')
        entry=ctk.CTkEntry(field,textvariable=variables[key],width=55);entry.pack(side='right',padx=4)
        slider=ctk.CTkSlider(field,from_=low,to=high,number_of_steps=int((high-low)*10),width=160,command=lambda value,key=key:variables[key].set(f'{value:.1f}'))
        slider.set(float(style[key]));slider.pack(side='left',padx=4);sliders.append(slider)
        def sync_slider(*_,key=key,slider=slider,low=low,high=high):
            try:value=float(variables[key].get())
            except ValueError:return
            if low<=value<=high:slider.set(value)
        variable_traces.append((variables[key],variables[key].trace_add('write',sync_slider)))
    ctk.CTkLabel(left,text=app.t('لون الخط','Font color')).grid(row=6,column=0,pady=(16,4))
    ctk.CTkEntry(left,textvariable=variables['color'],width=180).grid(row=7,column=0,padx=12)
    def choose_color():
        try:initial=normalize_style({key:var.get() for key,var in variables.items()})['color']
        except ValueError:initial='#FFFFFF'
        selected=colorchooser.askcolor(parent=window,initialcolor=initial)[1]
        if selected:variables['color'].set(selected)
    app.ghost_button(left,app.t('اختيار اللون','Choose color'),choose_color).grid(row=8,column=0,pady=6)
    ctk.CTkLabel(left,text=app.t('موضع الترجمة','Subtitle position')).grid(row=9,column=0,pady=(12,4))
    positions={'bottom':app.t('أسفل الفيديو','Bottom'),'top':app.t('أعلى الفيديو','Top')}
    window._position_menu=CodedOptionMenu(left,variable=variables['position'],labels=positions)
    window._position_menu.grid(row=10,column=0,padx=12)
    window._style_sliders=sliders
    displayed_size=[None]
    def fit_preview(event=None):
        source=getattr(window,'_preview_source',None)
        if source is None:return
        available=(max(1,min(700,preview.winfo_width()-24)),max(1,min(440,preview.winfo_height()-24)))
        if available==displayed_size[0]:return
        displayed_size[0]=available
        image=ImageOps.contain(source,available)
        window._preview_image=ctk.CTkImage(image,size=image.size)
        preview.configure(image=window._preview_image,text='')
    preview.bind('<Configure>',fit_preview,add='+')
    changed=threading.Event();requests=queue.Queue(maxsize=1);pending=[None];revision=[0];worker=[None];trace_id=[None]
    def checkpoint():
        if changed.is_set() or app.local_tasks.closed:raise RuntimeError('Cancelled by user')
    def values():return normalize_style({key:var.get() for key,var in variables.items()})
    def work():
        while not changed.is_set():
            try:token,media,selected,subtitle=requests.get(timeout=.2)
            except queue.Empty:continue
            try:
                from translator.video_renderer import preview_subtitles
                with tempfile.TemporaryDirectory(prefix='veyora-live-preview-') as folder:
                    output=Path(folder)/'preview.png'
                    preview_subtitles(media or None,output,selected,checkpoint,subtitle_file=subtitle)
                    with Image.open(output) as img:image=img.copy()
                def done(token=token,image=image,media=media):
                    if changed.is_set() or token!=revision[0]:return
                    window._preview_source=image
                    displayed_size[0]=None;fit_preview()
                    window._preview_revision=token
                    status.configure(text=app.t('إطار من الفيديو بإعدادات التصدير نفسها.','Video frame with the export styling.') if media else app.t('خلفية تجريبية؛ اختر فيديو لمعاينته.','Sample background; select a video to preview it.'))
                app._ui_callbacks.put(done)
            except Exception as exc:
                if changed.is_set():return
                from runtime_support import friendly_error
                message=friendly_error(exc,app.is_arabic)
                def failed(token=token,message=message):
                    if not changed.is_set() and token==revision[0]:status.configure(text=app.t(message,message))
                app._ui_callbacks.put(failed)
    def refresh():
        pending[0]=None
        try:selected=values()
        except (ValueError,TypeError):
            status.configure(text=app.t('أدخل قيمًا ضمن الحدود ولونًا مثل #FFFFFF.','Enter values in range and a color like #FFFFFF.'));return
        media=path.get().strip().strip('"')
        if media.lower().endswith('.srt'):subtitle=media;media=''
        else:
            task=app.local_tasks.snapshot('Translation')
            subtitle=(task.result or {}).get('subtitle') if task and task.status=='completed' else None
        revision[0]+=1
        request=(revision[0],media,selected,subtitle)
        try:requests.get_nowait()
        except queue.Empty:pass
        requests.put_nowait(request)
        status.configure(text=app.t('جارٍ تحديث المعاينة…','Updating preview…'))
        if worker[0] is None:
            worker[0]=threading.Thread(target=work,daemon=True,name='live-subtitle-preview');worker[0].start()
    def schedule(*_):
        if changed.is_set():return
        if pending[0]:window.after_cancel(pending[0])
        pending[0]=window.after(350,refresh)
    def save():
        try:
            app.settings['subtitle_style']=values()
            from main import SettingsManager
            SettingsManager.save(app.settings)
            status.configure(text=app.t('حُفظت الإعدادات.','Settings saved.'))
        except (ValueError,TypeError):status.configure(text=app.t('تحقق من القيم أولًا.','Check the entered values.'))
    window._save_button=app.button(left,app.t('حفظ الإعدادات','Save settings'),save);window._save_button.grid(row=11,column=0,pady=16,padx=12)
    window._preview_button=app.ghost_button(left,app.t('تحديث المعاينة','Refresh preview'),refresh);window._preview_button.grid(row=12,column=0,pady=4)
    window._style_controls=variables;window._preview_revision=0
    for var in variables.values():variable_traces.append((var,var.trace_add('write',schedule)))
    trace_id[0]=path.trace_add('write',schedule)
    def destroy(event):
        if event.widget is not window:return
        changed.set()
        if pending[0]:
            try:window.after_cancel(pending[0])
            except Exception:pass
        try:path.trace_remove('write',trace_id[0])
        except Exception:pass
        for variable,token in variable_traces:
            try:variable.trace_remove('write',token)
            except Exception:pass
        variable_traces.clear()
    window.bind('<Destroy>',destroy,add='+');schedule()
