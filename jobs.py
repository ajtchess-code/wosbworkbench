"""Background job manager: progress, cancellation, logs and history.

Replaces bare threads that gave no progress, no cancel and only a popup at the
end. Workers receive a ``JobContext`` and may call ``ctx.progress(fraction, msg)``,
``ctx.log(line)`` and check ``ctx.cancelled``. The UI polls ``snapshot()``.
"""
from __future__ import annotations

import itertools
import threading
import time
import traceback
from dataclasses import dataclass, field


class JobCancelled(Exception):
    pass


@dataclass
class Job:
    id: int
    name: str
    status: str = 'queued'          # queued, running, done, failed, cancelled
    progress: float | None = None   # 0..1, None = indeterminate
    message: str = ''
    started: float = 0.0
    finished: float = 0.0
    error: str = ''
    traceback: str = ''
    output: str = ''                # file/folder the user may want to open
    result: object = None
    log: list = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event)

    @property
    def active(self):
        return self.status in ('queued', 'running')

    def elapsed(self):
        if not self.started:
            return 0.0
        return (self.finished or time.time()) - self.started


class JobContext:
    def __init__(self, job, manager):
        self.job = job; self._manager = manager

    @property
    def cancelled(self):
        return self.job.cancel_event.is_set()

    @property
    def cancel_event(self):
        return self.job.cancel_event

    def check(self):
        if self.cancelled:
            raise JobCancelled()

    def progress(self, fraction=None, message=None):
        with self._manager._lock:
            if fraction is not None:
                self.job.progress = max(0.0, min(1.0, float(fraction)))
            if message is not None:
                self.job.message = str(message)[:300]

    def log(self, line):
        with self._manager._lock:
            self.job.log.append(str(line)[:2000])
            if len(self.job.log) > 2000:
                del self.job.log[:500]
            self.job.message = str(line)[:300]

    def set_output(self, path):
        self.job.output = str(path)


class JobManager:
    def __init__(self, *, history=100, logger=None):
        self._lock = threading.RLock()
        self._ids = itertools.count(1)
        self.jobs = []
        self.history = history
        self.logger = logger
        self._listeners = []

    def on_change(self, callback):
        """callback(job) is called from the WORKER thread; marshal to UI yourself."""
        self._listeners.append(callback)

    def _notify(self, job):
        for callback in list(self._listeners):
            try:
                callback(job)
            except Exception:
                pass

    def submit(self, name, fn, *, on_done=None, on_error=None):
        """Run fn(ctx) in a daemon thread. on_done(result) / on_error(job) run in the worker
        thread too; the GUI wraps them to post back to the Tk thread."""
        job = Job(next(self._ids), str(name))
        with self._lock:
            self.jobs.append(job)
            finished = [j for j in self.jobs if not j.active]
            while len(finished) > self.history:
                self.jobs.remove(finished.pop(0))
        ctx = JobContext(job, self)

        def run():
            job.status = 'running'; job.started = time.time(); self._notify(job)
            if self.logger:
                self.logger.info('Job %s started: %s', job.id, job.name)
            try:
                job.result = fn(ctx)
                job.status = 'cancelled' if job.cancel_event.is_set() else 'done'
                if job.progress is not None:
                    job.progress = 1.0
            except JobCancelled:
                job.status = 'cancelled'
            except Exception as exc:
                job.status = 'failed'; job.error = f'{type(exc).__name__}: {exc}'
                job.traceback = traceback.format_exc()
                if self.logger:
                    self.logger.error('Job %s failed: %s\n%s', job.id, job.name, job.traceback)
            job.finished = time.time()
            if self.logger and job.status != 'failed':
                self.logger.info('Job %s %s after %.1fs', job.id, job.status, job.elapsed())
            self._notify(job)
            try:
                if job.status == 'done' and on_done:
                    on_done(job.result)
                elif job.status == 'failed' and on_error:
                    on_error(job)
            except Exception:
                if self.logger:
                    self.logger.exception('Job %s completion handler failed', job.id)

        threading.Thread(target=run, name=f'job-{job.id}', daemon=True).start()
        return job

    def cancel(self, job_id):
        with self._lock:
            for job in self.jobs:
                if job.id == job_id and job.active:
                    job.cancel_event.set(); job.message = 'Cancelling…'
                    return True
        return False

    def active(self):
        with self._lock:
            return [j for j in self.jobs if j.active]

    def snapshot(self):
        with self._lock:
            return [{'id': j.id, 'name': j.name, 'status': j.status, 'progress': j.progress,
                     'message': j.message, 'elapsed': round(j.elapsed(), 1), 'output': j.output,
                     'error': j.error} for j in reversed(self.jobs)]

    def get(self, job_id):
        with self._lock:
            return next((j for j in self.jobs if j.id == job_id), None)

    def wait(self, job, timeout=None):
        """Test helper: block until the job finishes."""
        end = None if timeout is None else time.time() + timeout
        while job.active:
            if end and time.time() > end:
                return False
            time.sleep(0.01)
        return True
