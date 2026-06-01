"""
Background worker that fetches latest Maven Central versions for a list of
MavenDependencyInfo objects.  Only fetches deps that have an explicit version
(managed deps are skipped).
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from core.maven_registry import fetch_latest_version, MavenFetchError, MavenNotFoundError
from core.npm_cache import NpmCache
from models.maven_dependency import MavenDependencyInfo


def _cache_key(dep: MavenDependencyInfo) -> str:
    return f"maven:{dep.coordinate}"


class MavenFetchWorker(QObject):
    package_ready = pyqtSignal(str, str)   # coordinate, latest_version
    progress      = pyqtSignal(int, int)   # completed, total
    error         = pyqtSignal(str, str)   # coordinate, message
    finished      = pyqtSignal()

    def __init__(
        self,
        packages: list[MavenDependencyInfo],
        cache: NpmCache | None = None,
        cache_ttl_hours: int = 24,
        bypass_cache: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._packages  = packages
        self._cache     = cache
        self._ttl       = cache_ttl_hours
        self._bypass    = bypass_cache
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        fetchable = [p for p in self._packages if not p.is_managed]
        total = len(fetchable)

        for i, dep in enumerate(fetchable):
            if self._cancelled:
                break

            key = _cache_key(dep)

            if not self._bypass and self._cache:
                cached = self._cache.get(key, "", self._ttl)
                if cached is not None:
                    latest = cached.get("latest_version", "")
                    if latest:
                        self.package_ready.emit(dep.coordinate, latest)
                        self.progress.emit(i + 1, total)
                        continue

            try:
                latest = fetch_latest_version(dep.group_id, dep.artifact_id)
                if self._cache:
                    self._cache.set(key, "", {"latest_version": latest})
                self.package_ready.emit(dep.coordinate, latest)
            except MavenNotFoundError:
                # Package is not on Maven Central (private registry etc.) —
                # emit with empty string so the table shows "—" instead of Error.
                self.package_ready.emit(dep.coordinate, "")
            except MavenFetchError as exc:
                self.error.emit(dep.coordinate, str(exc))
            except Exception as exc:  # noqa: BLE001
                self.error.emit(dep.coordinate, f"Unexpected error: {exc}")

            self.progress.emit(i + 1, total)

        if self._cache:
            self._cache.flush()

        self.finished.emit()
