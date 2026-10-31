"""Canvas-backed Arabic/English confirmation; no shaped text in native Win32 dialogs."""
import customtkinter as ctk


def confirm(app,ar_title,en_title,ar_body,en_body,on_yes,on_no=None):
    existing=getattr(app,'_confirm_controls',None)
    if existing and existing['window'].winfo_exists():
        existing['window'].lift();return existing
    # Keep one modal per application. Destroying a newly created transient before
    # its queued Windows mapping/focus events ran crashed the native Tk loop.
    # Reuse also bounds CTkToplevel's global focus bindings and titlebar timers.
    controls=getattr(app,'_confirmation_window',None)
    if controls is None:
        window=ctk.CTkToplevel(app)
        window.geometry('640x300');window.minsize(540,260);window.transient(app);window.configure(fg_color=app.c['bg'])
        window.grid_columnconfigure(0,weight=1);window.grid_rowconfigure(0,weight=1)
        label=ctk.CTkLabel(window,wraplength=560,justify=app._justify(),anchor=app._anchor(),font=('Segoe UI',14))
        label.grid(row=0,column=0,sticky='nsew',padx=24,pady=18)
        buttons=ctk.CTkFrame(window,fg_color='transparent');buttons.grid(row=1,column=0,pady=18)
        yes=app.button(buttons,app.t('نعم','Yes'),None,width=150);yes.pack(side='right',padx=8)
        no=app.ghost_button(buttons,app.t('لا','No'),None,width=150);no.pack(side='right',padx=8)
        controls=app._confirmation_window=dict(window=window,yes=yes,no=no,label=label)
    window,yes,no,label=(controls[key] for key in ('window','yes','no','label'))
    window.title(ar_title if app.is_arabic else en_title)
    label.configure(text=app.t(ar_body,en_body),justify=app._justify(),anchor=app._anchor())
    resolved=False
    def finish(accepted):
        nonlocal resolved
        if resolved:return
        resolved=True
        yes.configure(state='disabled');no.configure(state='disabled')
        window.grab_release();window.withdraw();app._confirm_controls=None
        if accepted:on_yes()
        elif on_no:on_no()
    yes.configure(text=app.t('نعم','Yes'),command=lambda:finish(True),state='normal')
    no.configure(text=app.t('لا','No'),command=lambda:finish(False),state='normal')
    window.protocol('WM_DELETE_WINDOW',lambda:finish(False));window.deiconify();window.lift();window.grab_set()
    app._confirm_controls=controls
    return controls
