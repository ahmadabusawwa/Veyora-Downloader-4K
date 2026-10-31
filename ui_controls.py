"""Keep canvas-shaped labels out of native Windows dropdowns."""
import sys
import unicodedata
import customtkinter as ctk


def native_label(text):
    if any('\ufb50'<=c<='\ufeff' for c in text):
        from bidi.algorithm import get_display
        return unicodedata.normalize('NFKC',get_display(text))
    return text


class OptionMenu(ctk.CTkOptionMenu):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self._repair_native_labels()

    def _repair_native_labels(self):
        if not sys.platform.startswith('win'):return
        for index,value in enumerate(self._values):
            self._dropdown_menu.entryconfigure(index,label=native_label(value))
        self._repair_selected_label()

    def _repair_selected_label(self):
        # CTkOptionMenu uses tkinter.Label for its selected value, unlike the
        # surrounding shaped canvas text. Windows renders logical RTL here.
        if sys.platform.startswith('win') and hasattr(self,'_text_label'):
            self._text_label.configure(text=native_label(self._current_value))

    def _dropdown_callback(self,value):
        super()._dropdown_callback(value);self._repair_selected_label()

    def _variable_callback(self,*args):
        super()._variable_callback(*args);self._repair_selected_label()

    def set(self,value):
        super().set(value);self._repair_selected_label()

    def configure(self,**kwargs):
        super().configure(**kwargs)
        if 'values' in kwargs:self._repair_native_labels()
        else:self._repair_selected_label()


class CodedOptionMenu(OptionMenu):
    """Persist canonical codes while showing independently localized labels."""
    def __init__(self,master,*,variable,labels,**kwargs):
        self._canonical=variable;self._labels=labels
        self._display=ctk.StringVar(master=master,value=labels.get(variable.get(),next(iter(labels.values()))))
        reverse={value:key for key,value in labels.items()}
        command=kwargs.pop('command',None)
        def select(value):
            variable.set(reverse[value])
            if command:command(reverse[value])
        super().__init__(master,variable=self._display,values=list(labels.values()),command=select,**kwargs)
        self._trace=variable.trace_add('write',lambda *_:self._display.set(labels.get(variable.get(),variable.get())))

    def destroy(self):
        try:self._canonical.trace_remove('write',self._trace)
        except Exception:pass
        super().destroy()
