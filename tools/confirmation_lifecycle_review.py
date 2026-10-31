"""Real Windows Tk loops: compare archived transient lifecycle with the fix."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def child(mode,report_path):
    import faulthandler
    with report_path.with_suffix('.log').open('w',encoding='utf8') as trace:
        faulthandler.enable(file=trace,all_threads=True)
        from desktop_ui import DesktopApp
        from navigation_validation import PAGES,press_page
        from confirmation import confirm
        if mode=='before':
            scope={}
            exec((ROOT/'tools/fixtures/confirmation_before.py').read_text(),scope)
            confirm=scope['confirm']
        app=DesktopApp();app.settings['ui_language']='en'
        state=dict(round=0,callbacks=0)
        def finish():
            report_path.write_text(json.dumps(state),encoding='utf8');app._on_close()
        def accepted():
            state['callbacks']+=1
            app.show_tab('Downloads')
        def cycle():
            for page in PAGES:press_page(app,page)
            confirm(app,'تأكيد','Confirm','تجربة','Actual lifecycle test',accepted)
            controls=app._confirm_controls
            controls['yes'].invoke()
            state['round']+=1
            if state['round']==10:app.after(100,finish)
            else:app.after(75,cycle)
        app.after(100,cycle);app.mainloop()
        faulthandler.disable()


def main():
    if len(sys.argv)==4 and sys.argv[1]=='--child':
        child(sys.argv[2],Path(sys.argv[3]));return
    folder=ROOT/'dist/confirmation-lifecycle';folder.mkdir(parents=True,exist_ok=True)
    records=[]
    for mode in ('before','after'):
        for iteration in range(3):
            path=folder/f'{mode}-{iteration}.json'
            with tempfile.TemporaryDirectory(prefix='veyora-confirmation-') as config:
                Path(config,'settings.json').write_text('{"auto_update_check":false}',encoding='utf8')
                env=dict(os.environ,VEYORA_CONFIG_DIR=config)
                result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--child',mode,str(path)],
                    cwd=ROOT,env=env,capture_output=True,text=True,timeout=45)
            row=dict(mode=mode,iteration=iteration,exit=result.returncode,
                result=json.loads(path.read_text()) if path.exists() else None)
            records.append(row);print(json.dumps(row),flush=True)
    (ROOT/'dist/confirmation-lifecycle-results.json').write_text(json.dumps(records,indent=2),encoding='utf8')
    if not all(row['exit']==0 and row['result']==dict(round=10,callbacks=10) for row in records if row['mode']=='after'):
        raise RuntimeError('Fixed confirmation lifecycle did not pass actual Tk mainloops')


if __name__=='__main__':main()
