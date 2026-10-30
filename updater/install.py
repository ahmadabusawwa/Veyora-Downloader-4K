"""Second process: wait for parent exit, reverify, then run the per-user installer."""
import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from .core import TRUSTED_KEYS, verify_manifest, verify_file, UpdateError

def install_after_exit(parent_pid, installer, tag, config_dir):
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        raise UpdateError('Installing updates requires the packaged Windows application')
    path = Path(installer).resolve()
    root = (Path(config_dir) / 'updates').resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise UpdateError('Installer outside update staging directory')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, int(parent_pid))
    if not handle and ctypes.get_last_error() != 87:
        raise UpdateError('Could not confirm application exit; installation blocked')
    if handle:
        try:
            if kernel.WaitForSingleObject(handle, 120000) != 0:
                raise UpdateError('Application did not exit; installation cancelled')
        finally:
            kernel.CloseHandle(handle)
    m = verify_manifest((path.parent/'update-manifest.json').read_bytes(), (path.parent/'update-manifest.sig').read_bytes(), TRUSTED_KEYS, tag)
    verify_file(path, m)
    journal = Path(config_dir) / 'update-status.json'
    journal.write_text(json.dumps({'version':tag,'state':'installing','time':time.time()}), encoding='utf8')
    subprocess.Popen([str(path), '/NORESTART', '/CURRENTUSER'], shell=False)
    journal.write_text(json.dumps({'version':tag,'state':'handed-off','time':time.time()}), encoding='utf8')
    # Exit immediately so this helper also releases the installed executable/DLLs.
    # Success is confirmed from the running version at the next application start.
    return 0
