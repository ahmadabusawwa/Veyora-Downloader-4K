"""Open only existing final outputs, off the Tk thread."""
from pathlib import Path
import os
import subprocess
import sys
import threading


SAFE_OUTPUT_SUFFIXES=frozenset(('.mp4','.mkv','.mov','.avi','.webm','.mp3','.wav','.m4a','.flac','.aac','.ogg','.opus','.srt','.vtt','.ass','.ssa','.txt','.log'))


def validate_open_target(path,folder=False):
    file=Path(path).resolve()
    if not file.is_file():raise FileNotFoundError(str(file))
    if not folder and file.suffix.lower() not in SAFE_OUTPUT_SUFFIXES:
        raise ValueError('Unsafe output type; open its folder to inspect the file')
    return file


def launch_output(app, path, folder=False):
    def work():
        try:
            file = validate_open_target(path,folder)
            if folder:
                if os.name=='nt':
                    subprocess.Popen([str(Path(os.environ.get('SystemRoot','C:/Windows'))/'explorer.exe'),'/select,',str(file)])
                else:
                    subprocess.Popen(['open' if sys.platform=='darwin' else 'xdg-open',str(file.parent)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            elif os.name == 'nt':
                try:os.startfile(str(file))
                except OSError as exc:
                    if file.suffix.lower()=='.srt' and getattr(exc,'winerror',None)==1155:
                        subprocess.Popen([str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32'/'notepad.exe'),str(file)])
                    else:raise
            else:
                subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open',str(file)],
                                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if not hasattr(app,'_opened_outputs'):app._opened_outputs=[]
            app._opened_outputs.append(dict(path=str(file),folder=folder))
        except Exception as exc:
            from runtime_support import friendly_error
            message = friendly_error(exc,app.is_arabic)
            app._ui_callbacks.put(lambda:app.notify(message,message,'error') if not getattr(app,'_closing',False) else None)
    threading.Thread(target=work,daemon=True,name='open-final-output').start()


def final_output(task, action):
    if task.get('status') != 'Completed':
        return None
    return task.get('subtitle_file') if action == 'subtitle' else task.get('downloaded_file')
