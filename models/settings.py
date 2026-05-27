from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QSettings

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

    # ── resolved theme ────────────────────────────────────────────────────────

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

    # ── persistence ───────────────────────────────────────────────────────────

    def load(self) -> None:
        s = _make_settings()
        self.min_age_days     = int(s.value("min_age_days",     self.min_age_days))
        self.cache_ttl_hours  = int(s.value("cache_ttl_hours",  self.cache_ttl_hours))
        self.last_opened_path = str(s.value("last_opened_path", self.last_opened_path))
        self.hide_uptodate      = s.value("hide_uptodate",      self.hide_uptodate,      type=bool)
        self.merge_patch_minor  = s.value("merge_patch_minor",  self.merge_patch_minor,  type=bool)
        try:
            self.recent_files = json.loads(s.value("recent_files", "[]"))
        except Exception:
            self.recent_files = []
        try:
            self.pending_installs = json.loads(s.value("pending_installs", "{}"))
        except Exception:
            self.pending_installs = {}

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
        s.setValue("hide_uptodate",     self.hide_uptodate)
        s.setValue("merge_patch_minor", self.merge_patch_minor)
        s.setValue("recent_files",     json.dumps(self.recent_files))
        s.setValue("pending_installs", json.dumps(self.pending_installs))
        s.remove("dark_mode")   # clean up migrated key
