"""
Controller that tracks the active package manager for the open project and
drives the picker dialog.  Exposed to QML as the ``Pm`` context property.

The heavy lifting (detection + persistence) lives in ``core.package_manager``
and ``AppSettings``; this class just holds the current selection, tells QML
when to prompt, and applies the user's choice.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot

from core.package_manager import PackageManager
from models.settings import AppSettings


class PackageManagerController(QObject):
    activeChanged = pyqtSignal()
    overridesChanged = pyqtSignal()       # a per-folder pin was added/changed
    showPicker = pyqtSignal(str)          # currentId — ask QML to open the dialog

    def __init__(self, settings: AppSettings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._project_dir = ""
        self._active = settings.active_package_manager("")   # global default at startup
        self._session_pm: PackageManager | None = None   # session-only pick, not persisted

    # ── exposed state ─────────────────────────────────────────────────────────

    @pyqtProperty(str, notify=activeChanged)
    def activeId(self) -> str:
        return self._active.id

    @pyqtProperty(str, notify=activeChanged)
    def activeName(self) -> str:
        return self._active.display

    @pyqtProperty(str, notify=activeChanged)
    def installCommand(self) -> str:
        return " ".join(self._active.install_cmd())

    @pyqtProperty(bool, notify=activeChanged)
    def hasOverride(self) -> bool:
        return bool(self._project_dir) and \
            self._settings.package_manager_override(self._project_dir) is not None

    # ── project tracking ──────────────────────────────────────────────────────

    @pyqtSlot(str)
    def setProject(self, project_dir: str) -> None:
        """Point at *project_dir*, re-resolve the manager, and prompt if the
        lockfiles are ambiguous and the user hasn't pinned a choice yet."""
        if project_dir == self._project_dir:
            return
        self._project_dir = project_dir
        self._session_pm = None          # new project clears any session-only pick
        detection = self._settings.resolve_package_manager(project_dir)
        self._active = self._settings.active_package_manager(project_dir)
        self.activeChanged.emit()
        if project_dir and detection.is_ambiguous:
            self.showPicker.emit(self._active.id)

    @pyqtSlot()
    def reevaluate(self) -> None:
        """Re-resolve the active manager for the current project without
        prompting — e.g. after the default or an override changed in Settings.
        A session-only pick (remember=False) is preserved."""
        if self._session_pm is not None:
            return
        self._active = self._settings.active_package_manager(self._project_dir)
        self.activeChanged.emit()

    # ── picker ────────────────────────────────────────────────────────────────

    @pyqtSlot()
    def requestPicker(self) -> None:
        """Open the picker on demand (from the toolbar badge)."""
        self.showPicker.emit(self._active.id)

    @pyqtSlot(str, bool)
    def choose(self, manager_id: str, remember: bool) -> None:
        """Apply the user's pick.  When *remember* is set, pin it to this folder;
        otherwise it applies only for the current session."""
        pm = PackageManager.from_id(manager_id)
        if pm is None:
            return
        if remember and self._project_dir:
            self._settings.set_package_manager_override(self._project_dir, pm.id)
            self._session_pm = None      # persisted — no longer session-only
            self.overridesChanged.emit()
        else:
            self._session_pm = pm        # track so reevaluate() doesn't overwrite it
        self._active = pm
        self.activeChanged.emit()

    @pyqtSlot(result="QVariantMap")
    def detectedLockfiles(self) -> dict:
        """``{manager_id: lockfile_name}`` for the current project's nearest
        lockfile directory — used by the dialog to show what was found."""
        found: dict[str, str] = {}
        if not self._project_dir:
            return found
        detection = self._settings.resolve_package_manager(self._project_dir)
        directory = detection.lockfile_dir or self._project_dir
        for pm in PackageManager:
            for lockfile in pm.lockfiles:
                if os.path.exists(os.path.join(directory, lockfile)):
                    found[pm.id] = lockfile
                    break
        return found
