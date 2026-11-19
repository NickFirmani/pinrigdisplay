"""Persist and run maintenance jobs for Linux services."""
import json
import logging
from pathlib import Path
import threading
import uuid


class Jobs:
    """One active job; retain its outcome across process restarts."""
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.worker = None
        self.value = {'state': 'idle'}
        if path.exists():
            self.value = json.loads(path.read_text())
            if self.value.get('state') == 'running':
                self.value.update(state='failed', error='Service restarted; inspect target and retry installation')
                self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.value))
        temporary.replace(self.path)

    def wait(self) -> None:
        """Drain maintenance before releasing service resources."""
        if self.worker is not None:
            self.worker.join()

    def status(self) -> dict:
        with self.lock:
            return dict(self.value)

    def phase(self, phase: str) -> None:
        with self.lock:
            self.value['phase'] = phase
            self._save()

    def start(self, action, *, launch=None) -> dict:
        with self.lock:
            if self.value['state'] == 'running':
                raise ValueError('maintenance already running')
            self.value = {'id': uuid.uuid4().hex, 'state': 'running', 'phase': 'queued'}
            self._save()
        def work():
            try:
                result = action(self.phase)
                with self.lock:
                    self.value.update(state='succeeded', result=result)
                    self._save()
            except Exception as error:
                logging.getLogger(__name__).exception('Maintenance job failed')
                with self.lock:
                    self.value.update(state='failed', error=str(error)[:500])
                    self._save()
        try:
            if launch:
                launch(work)
            else:
                self.worker = threading.Thread(target=work, daemon=False)
                self.worker.start()
        except Exception as error:
            with self.lock:
                self.value.update(state='failed', error=str(error)[:500])
                self._save()
            raise
        return self.status()
