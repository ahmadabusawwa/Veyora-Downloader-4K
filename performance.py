"""Explicit, bounded CPU/network budgets. Default preserves 1.7 behavior."""
import json
import os
from pathlib import Path
PROFILES={'economy':(2,1,1),'balanced':(4,3,2),'high':(8,5,4)}
def profile():
    name=os.environ.get('VEYORA_PERFORMANCE')
    if name is None:
        try:
            root=Path(os.environ.get('VEYORA_CONFIG_DIR',str(Path.home()/'.veyora')))
            name=json.loads((root/'settings.json').read_text(encoding='utf8')).get('performance_mode','balanced')
        except (OSError,ValueError,AttributeError):name='balanced'
    return PROFILES.get(name,PROFILES['balanced'])
def cpu_threads():
    # Leave scheduler capacity for Tk and Windows, especially on 2/4-core PCs.
    available = max(1, os.cpu_count() or 1)
    budget = max(1, available // 2)
    return min(profile()[0], budget)


def configure_worker():
    """Apply only inside a processing child, never lower the desktop UI priority."""
    threads = cpu_threads()
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
        os.environ[name] = str(threads)
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        # BELOW_NORMAL_PRIORITY_CLASS, not IDLE (which can starve useful work).
        kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x00004000)
    else:
        try:
            os.nice(5)
        except OSError:
            pass
    return threads

