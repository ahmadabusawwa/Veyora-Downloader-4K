"""Isolate native AI calls so cancellation can stop a blocked model load/inference."""
import multiprocessing
import os
import queue
import signal
import subprocess
import tempfile
import time
from .resources import processing_slot


def _pipeline_worker(media, output, options, cancelled, progress_queue, result, temporary):
    if os.name != 'nt':
        os.setsid()  # FFmpeg children share this job's process group.
    from performance import configure_worker
    configure_worker()
    tempfile.tempdir = temporary

    def checkpoint():
        if cancelled.is_set():
            raise RuntimeError('Cancelled by user')

    def progress(stage, fraction=None):
        try:
            progress_queue.put_nowait((stage, fraction))
        except queue.Full:
            pass

    try:
        from .pipeline import TranslationPipeline
        outputs = TranslationPipeline(media, output).run(
            checkpoint=checkpoint, progress=progress, **options)
        checkpoint()
        result.send(('ok', outputs))
    except BaseException as exc:
        from runtime_support import log_failure
        if not cancelled.is_set():
            log_failure(exc, 'translation subprocess')
        result.send(('error', str(exc)))
    finally:
        result.close()
        progress_queue.cancel_join_thread()


def _stop(process):
    if not process.is_alive():
        return
    if os.name == 'nt':
        # Stop the whole job, including an FFmpeg process started by the worker.
        try:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.SubprocessError):
            pass  # Fall through to killing the worker itself if taskkill failed.
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.is_alive():
        process.kill()
    process.join(timeout=5)


def run_translation(media, output, *, checkpoint=lambda: None,
                    progress=lambda stage, fraction=None: None, **options):
    with processing_slot(checkpoint, progress):
        checkpoint()
        context = multiprocessing.get_context('spawn')
        cancelled = context.Event()
        updates = context.Queue(maxsize=1)
        receiving, sending = context.Pipe(duplex=False)
        with tempfile.TemporaryDirectory(prefix='veyora-job-') as temporary:
            process = context.Process(target=_pipeline_worker,
                args=(str(media), str(output), options, cancelled, updates, sending, temporary),
                name='veyora-translation')
            process.start()
            sending.close()
            last_update = time.monotonic()
            last_stage = ('Preparing translation worker', None)
            try:
                while True:
                    checkpoint()
                    try:
                        last_stage = updates.get_nowait()
                        progress(*last_stage)
                        last_update = time.monotonic()
                    except queue.Empty:
                        pass
                    if time.monotonic() - last_update >= 1:
                        # Honest heartbeat: elapsed waiting is not completed media.
                        progress(last_stage[0] + ' | Working…', last_stage[1])
                        last_update = time.monotonic()
                    if receiving.poll(.1):
                        try:
                            status, payload = receiving.recv()
                        except EOFError as exc:
                            raise RuntimeError('Translation worker exited without a result') from exc
                        checkpoint()
                        if status != 'ok':
                            raise RuntimeError(payload)
                        return payload
                    if not process.is_alive():
                        raise RuntimeError('Translation worker exited without a result')
            finally:
                cancelled.set()
                process.join(timeout=2)
                try:
                    _stop(process)
                finally:
                    receiving.close()
                    updates.cancel_join_thread()
                    updates.close()
                    if not process.is_alive():
                        process.close()
