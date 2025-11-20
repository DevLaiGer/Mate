"""Process-wide helpers."""

from __future__ import annotations

from pathlib import Path

import portalocker


class SingleInstance:
    """Ensures only one copy of mate is running."""

    def __init__(self, lockfile: Path) -> None:
        self.lockfile = lockfile
        self._lock: portalocker.Lock | None = None

    def acquire(self) -> bool:
        self.lockfile.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._lock = portalocker.Lock(str(self.lockfile), timeout=0)
            self._lock.acquire()
            return True
        except portalocker.exceptions.LockException:
            return False

    def release(self) -> None:
        if self._lock:
            self._lock.release()
            self._lock = None

    def __enter__(self) -> SingleInstance:
        if not self.acquire():
            raise RuntimeError("another mate instance is already running")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        self.release()
