"""
Root controller exposed to QML as the ``App`` context property.

Owns the persistent :class:`AppSettings`, the resolved light/dark theme, and
the asynchronously-fetched ``node`` / ``npm`` version strings shown in the
status bar.  Screen-specific logic lives in dedicated controllers added in
later migration chunks.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from PyQt6.QtCore import (
    QObject, QThread, pyqtProperty, pyqtSignal, pyqtSlot,
)

from _version import VERSION
from core.node_env import node_path_env
from core.npm_cache import NpmCache
from core.package_manager import DEFAULT_MANAGER, PackageManager
from models.settings import AppSettings


def _fmt_ago(dt: datetime | None) -> str:
    if dt is None:
        return "never"
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    days = int(secs // 86400)
    if days == 1:
        return "yesterday"
    if days < 60:
        return f"{days}d ago"
    if days < 730:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


def _fmt_duration(secs: float) -> str:
    if secs < 3600:
        return f"{int(secs // 60)}m"
    if secs < 86400:
        return f"{int(secs // 3600)}h"
    days = int(secs // 86400)
    if days < 60:
        return f"{days}d"
    if days < 730:
        return f"{days // 30}mo"
    return f"{days // 365}y"


class _VersionFetcher(QObject):
    """Fetches ``node --version`` and ``<manager> --version`` on a background thread."""

    versions_ready = pyqtSignal(str, str, str)   # (manager_id, node_version, manager_version)

    def __init__(self, manager: PackageManager, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manager = manager

    def run(self) -> None:
        env = node_path_env()

        def _get(cmd: list[str]) -> str:
            # Resolve the binary against the augmented PATH (like the install
            # controller does) — a GUI launch's minimal PATH won't find node /
            # yarn / pnpm / bun by bare name otherwise.
            program = cmd[0]
            if sys.platform != "win32":
                program = shutil.which(cmd[0], path=env["PATH"]) or cmd[0]
            try:
                r = subprocess.run([program, *cmd[1:]], capture_output=True, text=True,
                                   timeout=6, env=env, shell=sys.platform == "win32")
                return r.stdout.strip() if r.returncode == 0 else ""
            except Exception:
                return ""

        node_v = _get(["node", "--version"])
        manager_v = _get(self._manager.version_cmd())
        self.versions_ready.emit(self._manager.id, node_v, manager_v)


class AppController(QObject):
    """Application-wide state and theme, bound to QML via the ``App`` property."""

    darkChanged = pyqtSignal()
    themeChanged = pyqtSignal()
    versionsChanged = pyqtSignal()
    displaySettingsChanged = pyqtSignal()
    settingsChanged = pyqtSignal()
    cacheChanged = pyqtSignal()
    pmSettingsChanged = pyqtSignal()
    flash = pyqtSignal(str)
    reFetchRequested = pyqtSignal()

    def __init__(self, settings: AppSettings | None = None, cache: NpmCache | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        if settings is None:
            settings = AppSettings()
            settings.load()
        self._settings = settings
        self._cache = cache if cache is not None else NpmCache()
        self._cache_revision = 0

        self._node_version = ""
        self._manager_version = ""
        self._active_manager = (PackageManager.from_id(self._settings.default_package_manager)
                                or DEFAULT_MANAGER)
        self._ver_jobs: list[tuple[QThread, _VersionFetcher]] = []
        self._start_version_fetch(self._active_manager)

    # ── theme ──────────────────────────────────────────────────────────────────

    @pyqtProperty(bool, notify=darkChanged)
    def dark(self) -> bool:
        return self._settings.dark_mode

    @pyqtProperty(str, notify=themeChanged)
    def theme(self) -> str:
        return self._settings.theme

    @pyqtSlot(str)
    def setTheme(self, value: str) -> None:
        if value not in ("system", "light", "dark") or value == self._settings.theme:
            return
        was_dark = self._settings.dark_mode
        self._settings.theme = value
        self._settings.save()
        self.themeChanged.emit()
        if self._settings.dark_mode != was_dark:
            self.darkChanged.emit()
        self.flash.emit("✓  Theme saved")

    # ── display settings (read here, mutated by the settings page) ─────────────

    @pyqtProperty(bool, notify=displaySettingsChanged)
    def mergePatchMinor(self) -> bool:
        return self._settings.merge_patch_minor

    @pyqtProperty(int, notify=displaySettingsChanged)
    def oldAgeThresholdDays(self) -> int:
        return self._settings.old_version_threshold_days

    # ── settings-form values (read by the settings page) ───────────────────────

    @pyqtProperty(int, notify=settingsChanged)
    def minAgeDays(self) -> int:
        return self._settings.min_age_days

    @pyqtProperty(int, notify=settingsChanged)
    def cacheTtlHours(self) -> int:
        return self._settings.cache_ttl_hours

    @pyqtProperty(int, notify=settingsChanged)
    def oldVersionThreshold(self) -> int:
        return self._settings.old_version_threshold

    @pyqtProperty(str, notify=settingsChanged)
    def oldVersionUnit(self) -> str:
        return self._settings.old_version_unit

    @pyqtProperty(int, notify=cacheChanged)
    def cacheRevision(self) -> int:
        return self._cache_revision

    # ── settings-form mutations ────────────────────────────────────────────────

    @pyqtSlot(bool)
    def setMergePatchMinor(self, value: bool) -> None:
        if self._settings.merge_patch_minor == value:
            return
        self._settings.merge_patch_minor = value
        self._settings.save()
        self.displaySettingsChanged.emit()
        self.flash.emit("✓  Display setting saved")

    @pyqtSlot(int)
    def saveAgeFilter(self, days: int) -> None:
        changed = self._settings.min_age_days != days
        self._settings.min_age_days = days
        self._settings.save()
        self.settingsChanged.emit()
        self.flash.emit("✓  Settings saved")
        if changed:
            self.reFetchRequested.emit()

    @pyqtSlot(int, str)
    def saveOldVersion(self, threshold: int, unit: str) -> None:
        self._settings.old_version_threshold = threshold
        self._settings.old_version_unit = unit if unit in ("months", "years") else "months"
        self._settings.save()
        self.settingsChanged.emit()
        self.displaySettingsChanged.emit()
        self.flash.emit("✓  Settings saved")

    @pyqtSlot(int)
    def saveCacheTtl(self, hours: int) -> None:
        self._settings.cache_ttl_hours = hours
        self._settings.save()
        self.settingsChanged.emit()
        self.cacheChanged.emit()
        self.flash.emit("✓  Settings saved")

    @pyqtSlot()
    def clearCache(self) -> None:
        self._cache.clear()
        self._cache_revision += 1
        self.cacheChanged.emit()
        self.flash.emit("✓  Cache cleared")

    @pyqtSlot(int, result=str)
    def cacheInfoFor(self, ttl: int) -> str:
        stats = self._cache.stats()
        count = stats["count"]
        newest_at = stats["newest_at"]
        oldest_at = stats["oldest_at"]
        if ttl == 0:
            return "Caching is disabled"
        if count == 0:
            return "No data cached yet"
        pkg = "package" if count == 1 else "packages"
        parts = [f"{count} {pkg} cached", f"last updated {_fmt_ago(newest_at)}"]
        if oldest_at is not None:
            expires_at = oldest_at + timedelta(hours=ttl)
            remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
            parts.append("refresh overdue" if remaining <= 0
                         else f"refreshes in {_fmt_duration(remaining)}")
        return " · ".join(parts)

    # ── package-manager settings ────────────────────────────────────────────────

    @pyqtProperty(str, notify=pmSettingsChanged)
    def defaultPackageManager(self) -> str:
        return self._settings.default_package_manager

    @pyqtSlot(str)
    def setDefaultPackageManager(self, manager_id: str) -> None:
        pm = PackageManager.from_id(manager_id)
        if pm is None or pm.id == self._settings.default_package_manager:
            return
        self._settings.default_package_manager = pm.id
        self._settings.save()
        self.pmSettingsChanged.emit()
        self.flash.emit("✓  Default package manager saved")

    @pyqtProperty("QVariantList", notify=pmSettingsChanged)
    def packageManagerOverrides(self) -> list:
        """The per-folder pins as ``[{path, manager, name}]``, sorted by path."""
        out = []
        for path, manager_id in sorted(self._settings.package_manager_overrides.items()):
            pm = PackageManager.from_id(manager_id)
            out.append({"path": path, "manager": manager_id,
                        "name": pm.display if pm else manager_id})
        return out

    @pyqtSlot(str)
    def removePackageManagerOverride(self, path: str) -> None:
        self._settings.clear_package_manager_override(path)
        self.pmSettingsChanged.emit()
        self.flash.emit("✓  Override removed")

    # ── versions ───────────────────────────────────────────────────────────────

    @pyqtProperty(str, notify=versionsChanged)
    def nodeVersion(self) -> str:
        return self._node_version

    @pyqtProperty(str, notify=versionsChanged)
    def managerVersion(self) -> str:
        return self._manager_version

    @pyqtProperty(str, constant=True)
    def appVersion(self) -> str:
        return VERSION

    @pyqtSlot(str)
    def refreshManagerVersion(self, manager_id: str) -> None:
        """Re-probe the version for a newly-active manager (called when the open
        project's package manager changes)."""
        pm = PackageManager.from_id(manager_id)
        if pm is None or pm is self._active_manager:
            return
        self._active_manager = pm
        self._manager_version = ""          # clear until the new probe returns
        self.versionsChanged.emit()
        self._start_version_fetch(pm)

    @pyqtSlot()
    def refreshVersions(self) -> None:
        """Re-probe node/manager versions (e.g. after an nvm switch)."""
        self._start_version_fetch(self._active_manager)

    def _start_version_fetch(self, manager: PackageManager) -> None:
        fetcher = _VersionFetcher(manager)
        thread = QThread(self)
        fetcher.moveToThread(thread)
        # Keep strong refs to BOTH the thread and the fetcher until the thread
        # finishes.  QThread.started fires after this method returns, so without
        # a retained reference the fetcher can be garbage-collected first and
        # run() would never execute.
        job = (thread, fetcher)
        self._ver_jobs.append(job)

        thread.started.connect(fetcher.run)
        # versions_ready carries the manager id so this stays a queued
        # connection to a real slot (delivered on the main thread), not a bare
        # lambda that would run in the worker thread.
        fetcher.versions_ready.connect(self._on_versions_fetched)
        fetcher.versions_ready.connect(thread.quit)
        fetcher.versions_ready.connect(fetcher.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._release_job(job))
        thread.start()

    def _release_job(self, job: tuple) -> None:
        if job in self._ver_jobs:
            self._ver_jobs.remove(job)

    @pyqtSlot(str, str, str)
    def _on_versions_fetched(self, manager_id: str, node_v: str, mgr_v: str) -> None:
        if manager_id == self._active_manager.id:      # ignore stale results
            self._node_version = node_v
            self._manager_version = mgr_v
        self.versionsChanged.emit()

    # ── lifecycle ──────────────────────────────────────────────────────────────

    @pyqtSlot()
    def shutdown(self) -> None:
        """Stop background threads cleanly before the process exits."""
        for thread, _fetcher in list(self._ver_jobs):
            try:
                thread.quit()
                thread.wait(2000)
            except RuntimeError:
                pass
        self._ver_jobs.clear()
