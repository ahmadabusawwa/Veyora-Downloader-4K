"""Central local-media state. Workers never own widgets or call Tcl/Tk."""
import copy
from dataclasses import dataclass, field
from pathlib import Path
import threading
import time
import uuid


@dataclass
class LocalTask:
    id: str
    kind: str
    path: str
    source: str
    target: str
    mode: str
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    status: str = 'running'
    stage: str = 'Task started, preparing…'
    fraction: float | None = None
    result: dict | None = None
    error: str | None = None
    revision: int = 0

    @property
    def elapsed(self):
        return max(0, (self.finished or time.monotonic()) - self.started)


class LocalTaskManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.tasks = {}
        self.latest = {}
        self.active_id = None
        self.last_id = None
        self.events = {}
        self.forms = {}
        self.closed = False
        self.launch_count = 0

    @property
    def busy(self):
        with self.lock:
            return self.active_id is not None

    def form(self, kind):
        with self.lock:
            return dict(self.forms.get(kind, {}))

    def save_form(self, kind, **values):
        with self.lock:
            self.forms.setdefault(kind, {}).update(values)

    def snapshot(self, kind=None):
        with self.lock:
            tid = self.latest.get(kind) if kind else (self.active_id or self.last_id)
            return copy.deepcopy(self.tasks.get(tid))

    def cancel(self, kind=None):
        with self.lock:
            task = self.tasks.get(self.active_id)
            if not task or task.status not in ('running', 'cancelling') or (kind is not None and task.kind != kind):
                return False
            task.status, task.stage = 'cancelling', 'Cancelling task…'
            task.revision += 1
            self.events[task.id].set()
            return True

    def start(self, kind, path, folder, source, target, mode, *, save_original=False, runner=None, options=None):
        options = copy.deepcopy(options)
        with self.lock:
            if self.closed or self.active_id:
                return None
            tid = uuid.uuid4().hex
            task = LocalTask(tid, kind, str(path), source, target, mode)
            self.tasks[tid] = task
            self.latest[kind] = self.last_id = self.active_id = tid
            event = self.events[tid] = threading.Event()
            # Only the latest task per kind is retained; navigation cannot grow task history.
            for old in list(self.tasks):
                if old not in self.latest.values():
                    self.tasks.pop(old, None)
                    self.events.pop(old, None)
            self.launch_count += 1

        def checkpoint():
            if event.is_set():
                raise RuntimeError('Cancelled by user')

        def progress(stage, fraction=None):
            with self.lock:
                if task.status == 'cancelling':
                    return
                task.stage = str(stage)
                task.fraction = fraction
                task.revision += 1

        def work():
            try:
                perform = runner or run_local_job
                result = perform(kind, path, folder, source, target, mode,
                                 checkpoint=checkpoint, progress=progress, save_original=save_original, **({"options": copy.deepcopy(options)} if options else {}))
                checkpoint()
                with self.lock:
                    if event.is_set():
                        raise RuntimeError('Cancelled by user')
                    task.result, task.status, task.fraction = dict(result), 'completed', 1.0
                    task.stage = 'Saved: ' + ', '.join(result.values())
            except Exception as exc:
                from runtime_support import log_failure
                if not event.is_set():
                    log_failure(exc, 'local media')
                with self.lock:
                    task.error = str(exc)
                    task.status = 'cancelled' if event.is_set() else 'failed'
                    task.stage = 'Task cancelled.' if event.is_set() else 'Task failed.'
                    task.fraction = None
            finally:
                with self.lock:
                    task.finished = time.monotonic()
                    task.revision += 1
                    if self.active_id == tid:
                        self.active_id = None

        threading.Thread(target=work, daemon=True, name='local-media').start()
        return tid

    def close(self):
        with self.lock:
            self.closed = True
        self.cancel()


def run_local_job(kind, path, folder, source, target, mode, *, checkpoint, progress, save_original, options=None):
    if kind == 'Translation':
        from translator.worker import run_translation
        return run_translation(path, folder, mode=mode, checkpoint=checkpoint, progress=progress,
                               source_lang=source, target_lang=target, save_original=save_original, **(options or {}))
    import tempfile
    from translator.video_renderer import run_ffmpeg, media_duration
    from translator.pipeline import _publish_file
    destination = Path(folder) / (Path(path).stem + '.' + uuid.uuid4().hex[:12] + '.' + mode.lower())
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='veyora-convert-') as directory:
        temporary = Path(directory) / ('converted.' + mode.lower())
        from media_conversion import conversion_arguments
        arguments = conversion_arguments(mode, options or {})
        run_ffmpeg(['-i', str(path), *arguments, temporary], checkpoint, duration=media_duration(path),
                   progress=lambda fraction, eta, speed: progress('Converting media', fraction))
        _publish_file(temporary, destination, checkpoint)
    return {'video': str(destination)}
