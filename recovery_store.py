"""Crash-safe SQLite queue journal. One coalescing background writer, no Tk."""
import copy
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading


def recovery_path(config):
    override = os.environ.get('VEYORA_CONFIG_DIR')
    root = Path(override) if override else Path(os.environ.get('LOCALAPPDATA', config)) / 'Veyora Pro'
    return root / 'download-recovery.sqlite3'


class RecoveryStore:
    def __init__(self, path):
        self.path = Path(path)
        self.condition = threading.Condition()
        self.pending = None
        self.generation = self.saved = 0
        self.error = None
        self.closed = False
        self.thread = threading.Thread(target=self._write_loop, daemon=True, name='queue-journal')
        self.thread.start()

    def load(self):
        if not self.path.exists():
            return []
        with sqlite3.connect(self.path, timeout=5) as db:
            try:
                rows = db.execute('SELECT payload FROM tasks ORDER BY position').fetchall()
            except sqlite3.OperationalError as exc:
                if 'no such table' in str(exc):
                    return []
                raise
        return [json.loads(row[0]) for row in rows]

    def submit(self, tasks):
        with self.condition:
            self.generation += 1
            self.pending = (self.generation, copy.deepcopy(tasks))
            self.condition.notify_all()
            return self.generation

    def flush(self, generation=None):
        with self.condition:
            target = self.generation if generation is None else generation
            self.condition.wait_for(lambda: self.saved >= target or self.error is not None, timeout=15)
            if self.error:
                raise RuntimeError('Download recovery journal could not be saved') from self.error
            if self.saved < target:
                raise TimeoutError('Download recovery journal timed out')

    def _write_loop(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.pending is not None or self.closed)
                if self.pending is None and self.closed:
                    return
                generation, tasks = self.pending
                self.pending = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with sqlite3.connect(self.path, timeout=10) as db:
                    db.execute('PRAGMA journal_mode=DELETE')
                    db.execute('PRAGMA synchronous=FULL')
                    db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, position INTEGER, payload TEXT NOT NULL)')
                    db.execute('DELETE FROM tasks')
                    db.executemany('INSERT INTO tasks VALUES (?,?,?)', [(t['id'], i, json.dumps(t, ensure_ascii=False, default=str)) for i, t in enumerate(tasks)])
                with self.condition:
                    self.saved = generation
                    self.condition.notify_all()
            except Exception as exc:
                logging.exception('Queue recovery journal failed')
                with self.condition:
                    self.error = exc
                    self.condition.notify_all()

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
