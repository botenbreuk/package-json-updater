from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QSettings

from core.package_manager import DEFAULT_MANAGER, Detection, PackageManager, detect

ORG = "42nl"
APP = "PackageJsonUpdater"
_MAX_RECENT = 10


def _make_settings() -> QSettings:
    """Return a QSettings instance pointing at the right location per platform."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / APP / "settings.ini"
    path.parent.mkdir(parents=True, exist_ok=True)
    return QSettings(str(path), QSettings.Format.IniFormat)


def _system_is_dark() -> bool:
    """Return True when the OS is currently in dark mode."""
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        pass
    # Fallback: infer from palette window-text lightness
    try:
        from PyQt6.QtGui import QPalette
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            return app.palette().color(QPalette.ColorRole.WindowText).lightness() > 128
    except Exception:
        pass
    return False


@dataclass
class AppSettings:
    min_age_days: int = 2
    cache_ttl_hours: int = 24
    last_opened_path: str = ""
    theme: str = "system"          # "light" | "dark" | "system"
    hide_uptodate: bool = True
    merge_patch_minor: bool = False
    recent_files: list = field(default_factory=list)
    # Each entry: {"path": str, "last_checked": str | None}
    pending_installs: dict = field(default_factory=dict)
    # {"path/to/package.json": ["dep-a", "dep-b"]}
    default_package_manager: str = "npm"    # global fallback: npm | yarn | pnpm | bun
    package_manager_overrides: dict = field(default_factory=dict)
    # {"path/to/project-dir": "npm" | "yarn" | "pnpm" | "bun"}
    old_version_threshold: int = 12   # number of months or years (0 = disabled)
    old_version_unit: str = "months"  # "months" | "years"

    # ── resolved theme ────────────────────────────────────────────────────────

    @property
    def old_version_threshold_days(self) -> int:
        """Threshold in days (0 when disabled)."""
        if self.old_version_threshold <= 0:
            return 0
        if self.old_version_unit == "years":
            return self.old_version_threshold * 365
        return self.old_version_threshold * 30

    @property
    def dark_mode(self) -> bool:
        """Resolved dark/light boolean — callers never need to check theme directly."""
        if self.theme == "dark":
            return True
        if self.theme == "light":
            return False
        return _system_is_dark()

    # ── recent-file helpers ───────────────────────────────────────────────────

    def add_recent(self, path: str) -> None:
        """Insert *path* at the front of the recent list (deduped, max _MAX_RECENT)."""
        self.recent_files = [r for r in self.recent_files if r.get("path") != path]
        self.recent_files.insert(0, {"path": path, "last_checked": None})
        self.recent_files = self.recent_files[:_MAX_RECENT]

    def update_last_checked(self, path: str) -> None:
        """Stamp *path* with the current time and persist immediately."""
        for entry in self.recent_files:
            if entry.get("path") == path:
                entry["last_checked"] = datetime.now().isoformat()
                break
        self.save()

    # ── package-manager selection ─────────────────────────────────────────────

    def package_manager_override(self, project_dir: str) -> str | None:
        """Return the pinned manager id for *project_dir*, or None if unset."""
        return self.package_manager_overrides.get(project_dir)

    def set_package_manager_override(self, project_dir: str, manager_id: str) -> None:
        """Pin *project_dir* to *manager_id* (validated) and persist immediately."""
        pm = PackageManager.from_id(manager_id)
        if pm is None or not project_dir:
            return
        self.package_manager_overrides[project_dir] = pm.id
        self.save()

    def clear_package_manager_override(self, project_dir: str) -> None:
        """Remove any pin for *project_dir* and persist if something changed."""
        if self.package_manager_overrides.pop(project_dir, None) is not None:
            self.save()

    def resolve_package_manager(self, project_dir: str) -> Detection:
        """Full detection for *project_dir*, honoring its override and the
        global default.  ``manager`` is None when multiple lockfiles make the
        choice ambiguous (the UI prompts in that case)."""
        return detect(
            project_dir,
            override=self.package_manager_override(project_dir),
            default=self.default_package_manager,
        )

    def active_package_manager(self, project_dir: str) -> PackageManager:
        """Concrete manager for driving CLI commands — never None.

        On ambiguity, prefer the global default when it is among the
        candidates, otherwise the first candidate (enum order)."""
        result = self.resolve_package_manager(project_dir)
        if result.manager is not None:
            return result.manager
        default_pm = PackageManager.from_id(self.default_package_manager) or DEFAULT_MANAGER
        if default_pm in result.candidates:
            return default_pm
        return result.candidates[0] if result.candidates else default_pm

    @staticmethod
    def _sanitize_manager(value: str) -> str:
        """Coerce a stored manager id to a supported one, defaulting to npm."""
        return (PackageManager.from_id(value) or DEFAULT_MANAGER).id

    @staticmethod
    def _sanitize_overrides(raw) -> dict:
        """Keep only override entries that name a supported manager."""
        if not isinstance(raw, dict):
            return {}
        clean: dict = {}
        for path, value in raw.items():
            pm = PackageManager.from_id(value)
            if pm is not None:
                clean[str(path)] = pm.id
        return clean

    # ── persistence ───────────────────────────────────────────────────────────

    def load(self) -> None:
        s = _make_settings()
        self.min_age_days     = int(s.value("min_age_days",     self.min_age_days))
        self.cache_ttl_hours  = int(s.value("cache_ttl_hours",  self.cache_ttl_hours))
        self.last_opened_path = str(s.value("last_opened_path", self.last_opened_path))
        self.hide_uptodate      = s.value("hide_uptodate",      self.hide_uptodate,      type=bool)
        self.merge_patch_minor  = s.value("merge_patch_minor",  self.merge_patch_minor,  type=bool)
        self.old_version_threshold = int(s.value("old_version_threshold", self.old_version_threshold))
        raw_unit = str(s.value("old_version_unit", self.old_version_unit))
        self.old_version_unit = raw_unit if raw_unit in ("months", "years") else "months"
        try:
            self.recent_files = json.loads(s.value("recent_files", "[]"))
        except Exception:
            self.recent_files = []
        try:
            self.pending_installs = json.loads(s.value("pending_installs", "{}"))
        except Exception:
            self.pending_installs = {}

        self.default_package_manager = self._sanitize_manager(
            str(s.value("default_package_manager", self.default_package_manager)))
        try:
            raw_overrides = json.loads(s.value("package_manager_overrides", "{}"))
        except Exception:
            raw_overrides = {}
        self.package_manager_overrides = self._sanitize_overrides(raw_overrides)

        # Read new "theme" key; migrate legacy "dark_mode" bool if present
        raw_theme = s.value("theme", None)
        if raw_theme in ("light", "dark", "system"):
            self.theme = raw_theme
        elif s.contains("dark_mode"):
            # Migrate from old boolean setting
            self.theme = "dark" if s.value("dark_mode", False, type=bool) else "light"
        # else: keep dataclass default ("system")

    def save(self) -> None:
        s = _make_settings()
        s.setValue("min_age_days",     self.min_age_days)
        s.setValue("cache_ttl_hours",  self.cache_ttl_hours)
        s.setValue("last_opened_path", self.last_opened_path)
        s.setValue("theme",            self.theme)
        s.setValue("hide_uptodate",          self.hide_uptodate)
        s.setValue("merge_patch_minor",      self.merge_patch_minor)
        s.setValue("old_version_threshold",  self.old_version_threshold)
        s.setValue("old_version_unit",       self.old_version_unit)
        s.setValue("recent_files",     json.dumps(self.recent_files))
        s.setValue("pending_installs", json.dumps(self.pending_installs))
        s.setValue("default_package_manager",   self.default_package_manager)
        s.setValue("package_manager_overrides", json.dumps(self.package_manager_overrides))
        s.remove("dark_mode")   # clean up migrated key
