"""Canvas-backed Arabic/English confirmation; no shaped text in native Win32 dialogs."""
import customtkinter as ctk


def confirm(app,ar_title,en_title,ar_body,en_body,on_yes,on_no=None):
    existing=getattr(app,'_confirm_controls',None)
    if existing and existing['window'].winfo_exists():
        existing['window'].lift();return existing
    window=ctk.CTkToplevel(app);window.title(ar_title if app.is_arabic else en_title)
    window.geometry('640x300');window.minsize(540,260);window.transient(app);window.configure(fg_color=app.c['bg'])
    window.grid_columnconfigure(0,weight=1);window.grid_rowconfigure(0,weight=1)
    label=ctk.CTkLabel(window,text=app.t(ar_body,en_body),wraplength=560,justify=app._justify(),anchor=app._anchor(),font=('Segoe UI',14))
    label.grid(row=0,column=0,sticky='nsew',padx=24,pady=18)
    buttons=ctk.CTkFrame(window,fg_color='transparent');buttons.grid(row=1,column=0,pady=18)
    def finish(accepted):
        window.destroy();app._confirm_controls=None
        if accepted:on_yes()
        elif on_no:on_no()
    yes=app.button(buttons,app.t('نعم','Yes'),lambda:finish(True),width=150);yes.pack(side='right',padx=8)
    no=app.ghost_button(buttons,app.t('لا','No'),lambda:finish(False),width=150);no.pack(side='right',padx=8)
    window.protocol('WM_DELETE_WINDOW',lambda:finish(False));window.grab_set()
    controls=app._confirm_controls=dict(window=window,yes=yes,no=no,label=label)
    return controls
