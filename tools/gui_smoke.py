"""Run a real native window, exercise navigation, and save a screenshot."""
import argparse, os, sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['VEYORA_CONFIG_DIR']=tempfile.mkdtemp(prefix='veyora-gui-review-')
import main
main.DEFAULT_SETTINGS['auto_update_check']=False
from desktop_ui import DesktopApp
from PIL import ImageGrab
p=argparse.ArgumentParser();p.add_argument('--output',default='gui-review.png');a=p.parse_args()
app=DesktopApp()
errors=[]
app.report_callback_exception=lambda *exc:errors.append(str(exc))
def check():
    try:
        for tab in ['Downloads','History','Settings','Translation','Convert','Dashboard']:
            app.show_tab(tab);app.update()
        app.home_mode(True);assert app.mode_var.get()=='Audio (Extract)'
        app.home_mode(False);assert app.mode_var.get()=='Video'
        app.toggle_language();app.update();app.toggle_language();app.update()
        for size in ('1080x760','1280x820','1536x980'):
            app.geometry(size);app.update()
        assert app.url_entry.winfo_exists()
        x,y=app.winfo_rootx(),app.winfo_rooty()
        ImageGrab.grab().crop((x,y,x+app.winfo_width(),y+app.winfo_height())).save(a.output)
        assert not errors, errors
        print('GUI navigation, resize and screenshot passed:',a.output)
    finally:app._on_close()
app.after(1500,check)
app.mainloop()
if errors:raise RuntimeError(errors)
