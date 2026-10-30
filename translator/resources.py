"""One heavy processing job at a time; downloads can still run concurrently."""
import threading
from contextlib import contextmanager

_processing_lock = threading.RLock()


@contextmanager
def processing_slot(checkpoint=lambda: None, progress=lambda stage, fraction=None: None):
    acquired = _processing_lock.acquire(blocking=False)
    if not acquired:
        progress('Waiting for another processing job (lower memory use)', None)
        while not _processing_lock.acquire(timeout=.1):
            checkpoint()
    try:
        checkpoint()
        yield
    finally:
        _processing_lock.release()
