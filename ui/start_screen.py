"""
Start screen — shown when no package.json is loaded.

Implemented as a QQuickWidget that loads qml/StartScreen.qml.
The public signal interface is identical to the original widget version
so no changes are needed in main_window.py.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtQuickWidgets import QQuickWidget


_QML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "qml", "StartScreen.qml")


class _StartBridge(QObject):
    """Thin QObject that QML talks to via the 'bridge' context property."""

    recentFilesChanged = pyqtSignal()

    # Forwarded to StartScreen signals
    openFolderRequested = pyqtSignal()
    openFileRequested   = pyqtSignal()
    fileSelected        = pyqtSignal(str)
    recentRemoved       = pyqtSignal(str)
    recentsCleared      = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._recent_files: list = []

    @pyqtProperty(list, notify=recentFilesChanged)
    def recentFiles(self) -> list:
        return list(self._recent_files)

    def set_recent(self, recent_files: list) -> None:
        self._recent_files = list(recent_files)
        self.recentFilesChanged.emit()

    @pyqtSlot()
    def openFolder(self) -> None:
        self.openFolderRequested.emit()

    @pyqtSlot()
    def openFile(self) -> None:
        self.openFileRequested.emit()

    @pyqtSlot(str)
    def openFilePath(self, path: str) -> None:
        self.fileSelected.emit(path)

    @pyqtSlot(str)
    def removeRecent(self, path: str) -> None:
        self.recentRemoved.emit(path)

    @pyqtSlot()
    def clearRecents(self) -> None:
        self.recentsCleared.emit()


class StartScreen(QQuickWidget):
    """
    QML-backed start screen.  Drop-in replacement for the previous widget
    version — same signals, same set_recent() method.

    Signals
    -------
    file_selected(path)
        User clicked a recent-file row.
    recent_removed(path)
        User clicked the × button on a recent-file row.
    recents_cleared()
        User clicked "Clear all".
    open_folder_requested()
        User clicked "Open Folder".
    open_file_requested()
        User clicked "Open package.json".
    """

    file_selected         = pyqtSignal(str)
    recent_removed        = pyqtSignal(str)
    recents_cleared       = pyqtSignal()
    open_folder_requested = pyqtSignal()
    open_file_requested   = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._bridge = _StartBridge(self)

        # Wire bridge actions → StartScreen signals
        self._bridge.openFolderRequested.connect(self.open_folder_requested)
        self._bridge.openFileRequested.connect(self.open_file_requested)
        self._bridge.fileSelected.connect(self.file_selected)
        self._bridge.recentRemoved.connect(self.recent_removed)
        self._bridge.recentsCleared.connect(self.recents_cleared)

        self.rootContext().setContextProperty("bridge", self._bridge)
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.setSource(QUrl.fromLocalFile(os.path.abspath(_QML)))

    # ── public API (same as original) ─────────────────────────────────────────

    def set_recent(self, recent_files: list) -> None:
        """Update the recent-file list shown in the QML view."""
        self._bridge.set_recent(recent_files)
