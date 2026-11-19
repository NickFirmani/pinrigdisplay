"""Durable, bounded interaction storage using synchronous SQLite transactions."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3


class InteractionStore:
    def __init__(self, path: Path, capacity: int = 8):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.capacity = capacity
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS interactions (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path)
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def append(self, value: dict) -> None:
        payload = json.dumps(value, sort_keys=True)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT payload FROM interactions WHERE id=?', (value['interaction_id'],)).fetchone()
            if existing:
                if existing[0] != payload:
                    raise ValueError('interaction ID conflict')
                return
            if db.execute('SELECT COUNT(*) FROM interactions').fetchone()[0] >= self.capacity:
                raise OSError('interaction storage full')
            db.execute('INSERT INTO interactions VALUES (?, ?)', (value['interaction_id'], payload))

    def pending(self) -> list[dict]:
        with self._connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT payload FROM interactions ORDER BY rowid')]

    def confirm(self, interaction_id: str) -> None:
        with self._connect() as db:
            db.execute('DELETE FROM interactions WHERE id=?', (interaction_id,))
