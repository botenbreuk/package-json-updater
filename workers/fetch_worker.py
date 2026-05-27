"""
Background QThread worker that fetches npm registry data for a list of packages.
Emits signals as each package result arrives so the UI can update incrementally.

Cache behaviour
---------------
Pass an ``NpmCache`` instance and a ``cache_ttl_hours`` value to enable
caching.  Set ``bypass_cache=True`` (Refresh button) to force fresh fetches
for all packages regardless of cached data.  Cache is flushed to disk after
the last package is processed.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from core.npm_cache import NpmCache
from core.npm_registry import fetch_package_data, resolve_updates, NpmFetchError
from models.dependency import DependencyInfo


class FetchWorker(QObject):
    """
    Move an instance of this to a QThread, then call run() via the thread's
    started signal.

    Signals
    -------
    package_ready(name, updates_dict)
        Emitted after a successful fetch or cache hit.
    progress(completed, total)
        Emitted after each package (success, cache hit, or error).
    error(name, message)
        Emitted when a fetch fails.
    finished()
        Emitted when all packages are processed (or after cancel).
    """

    package_ready = pyqtSignal(str, dict)
    progress = pyqtSignal(int, int)
    error = pyqtSignal(str, str)
    finished = pyqtSignal()

    def __init__(
        self,
        packages: list[DependencyInfo],
        min_age_days: int,
        cache: NpmCache | None = None,
        cache_ttl_hours: int = 24,
        bypass_cache: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._packages = packages
        self._min_age_days = min_age_days
        self._cache = cache
        self._cache_ttl_hours = cache_ttl_hours
        self._bypass_cache = bypass_cache
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self._packages)
        for i, dep in enumerate(self._packages):
            if self._cancelled:
                break

            # ── cache hit ────────────────────────────────────────────────────
            if not self._bypass_cache and self._cache:
                cached = self._cache.get(dep.name, dep.current_version, self._cache_ttl_hours)
                if cached is not None:
                    self.package_ready.emit(dep.name, cached)
                    self.progress.emit(i + 1, total)
                    continue

            # ── live fetch ───────────────────────────────────────────────────
            try:
                registry_data = fetch_package_data(dep.name, self._min_age_days)
                updates = resolve_updates(dep.current_version, registry_data)
                if self._cache:
                    self._cache.set(dep.name, dep.current_version, updates)
                self.package_ready.emit(dep.name, updates)
            except NpmFetchError as exc:
                self.error.emit(dep.name, str(exc))
            except Exception as exc:  # noqa: BLE001
                self.error.emit(dep.name, f"Unexpected error: {exc}")

            self.progress.emit(i + 1, total)

        if self._cache:
            self._cache.flush()

        self.finished.emit()
