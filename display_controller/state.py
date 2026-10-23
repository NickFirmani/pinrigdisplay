"""Atomic persistence of the last successfully displayed page."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile

from .models import DisplayRequest, RequestValidationError


LOGGER = logging.getLogger(__name__)


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> DisplayRequest | None:
        """Return saved state, or ``None`` when it is missing or invalid."""
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return DisplayRequest.from_mapping(value)
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError, RequestValidationError) as error:
            LOGGER.warning("Ignoring invalid display state at %s: %s", self.path, error)
            return None

    def save(self, request: DisplayRequest) -> None:
        """Atomically replace the persisted state with *request*."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent, text=True
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as state_file:
                json.dump(request.to_dict(), state_file, separators=(",", ":"))
                state_file.write("\n")
                state_file.flush()
                os.fsync(state_file.fileno())
            os.chmod(temporary_path, 0o640)
            os.replace(temporary_path, self.path)
        finally:
            temporary_path.unlink(missing_ok=True)
