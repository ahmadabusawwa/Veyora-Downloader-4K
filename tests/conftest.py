import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['VEYORA_CONFIG_DIR'] = tempfile.mkdtemp(prefix='veyora-tests-config-')


# Tkinter variables must be finalized on their owning (main/UI) thread.
# Several GUI regression tests construct/destroy CTk roots in one pytest
# process. Their unreachable StringVars can otherwise be finalized by the
# next downloader worker during Python's cyclic GC, and Tk's __del__ blocks
# calling Tcl from that worker thread on Windows.
import gc
import threading
import pytest

@pytest.fixture(autouse=True)
def collect_tk_cycles_in_owner_thread():
    yield
    # A test may have destroyed its window, but retained references form
    # widget/variable cycles. Do not leave these to arbitrary network workers.
    if 'tkinter' in sys.modules and threading.current_thread() is threading.main_thread():
        gc.collect()
