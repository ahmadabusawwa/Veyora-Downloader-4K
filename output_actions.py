"""Open only existing final outputs, off the Tk thread."""
from pathlib import Path
import os
import subprocess
import sys
import threading


SAFE_OUTPUT_SUFFIXES=frozenset(('.flv','.wmv','.m4v','.mpeg','.mpg','.ts','.3gp','.sub','.sbv','.mp4','.mkv','.mov','.avi','.webm','.mp3','.wav','.m4a','.flac','.aac','.ogg','.opus','.srt','.vtt','.ass','.ssa','.txt','.log'))


def validate_open_target(path,folder=False):
    file=Path(path).resolve()
    if not file.is_file():raise FileNotFoundError(str(file))
    if not folder and file.suffix.lower() not in SAFE_OUTPUT_SUFFIXES:
        raise ValueError('Unsafe output type; open its folder to inspect the file')
    return file


def windows_association_present(suffix):
    """Query registered open handlers, without invoking the Open With chooser.

    https://learn.microsoft.com/windows/win32/api/shlwapi/nf-shlwapi-assocquerystringw
    Delegate handlers may have no executable (e.g. packaged Windows apps).
    """
    import ctypes
    from ctypes import wintypes
    function=ctypes.WinDLL('shlwapi',use_last_error=True).AssocQueryStringW
    function.argtypes=[wintypes.DWORD,ctypes.c_int,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    function.restype=ctypes.c_long
    for association in (2,18): # ASSOCSTR_EXECUTABLE or ASSOCSTR_DELEGATEEXECUTE
        buffer=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(len(buffer))
        if function(0x400,association,suffix,'open',buffer,ctypes.byref(size))==0 and buffer.value:
            if Path(buffer.value).name.casefold() not in ('openwith.exe','openwith'):
                return True
    return False


def open_windows_file(file):
    def notepad():
        return subprocess.Popen([str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32'/'notepad.exe'),str(file)])
    # ShellExecute can display Open With and report success rather than 1155.
    # Check first for SRT so a missing association never leaves an invisible
    # chooser obstructing the application's next native menu/dialog.
    if file.suffix.lower()=='.srt' and not windows_association_present('.srt'):
        return notepad()
    try:return os.startfile(str(file))
    except OSError as exc:
        if file.suffix.lower()=='.srt' and getattr(exc,'winerror',None)==1155:return notepad()
        raise


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
                open_windows_file(file)
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
