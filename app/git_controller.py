"""
Controller for git status (branch + commits-behind), background fetch / pull,
and the ``.nvmrc`` node-version hint.  Exposed to QML as the ``Git`` property.
"""
from __future__ import annotations

import os
import subprocess

from PyQt6.QtCore import (
    QObject, QThread, pyqtProperty, pyqtSignal, pyqtSlot,
)

from core.git_info import get_git_info, is_git_available


class _GitFetchWorker(QObject):
    finished = pyqtSignal()

    def __init__(self, directory: str) -> None:
        super().__init__()
        self._directory = directory

    def run(self) -> None:
        try:
            subprocess.run(["git", "-C", self._directory, "fetch"],
                           capture_output=True, timeout=15)
        except Exception:
            pass
        self.finished.emit()


class _GitPullWorker(QObject):
    finished = pyqtSignal(bool, str)   # success, error_message

    def __init__(self, directory: str) -> None:
        super().__init__()
        self._directory = directory

    def run(self) -> None:
        try:
            r = subprocess.run(["git", "-C", self._directory, "pull"],
                               capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                self.finished.emit(True, "")
            else:
                self.finished.emit(False, (r.stderr or r.stdout).strip())
        except Exception as exc:
            self.finished.emit(False, str(exc))


class GitController(QObject):
    changed = pyqtSignal()
    nvmrcChanged = pyqtSignal()
    pullFailed = pyqtSignal(str)
    reloadRequested = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._available = is_git_available()
        self._dir = ""
        self._branch = ""
        self._behind = 0
        self._has_repo = False
        self._fetching = False
        self._pulling = False
        self._node_version = ""
        self._nvmrc_text = ""
        self._nvmrc_warn = False
        self._fetch_pairs: set = set()
        self._pull_pairs: set = set()

    # ── properties ────────────────────────────────────────────────────────────

    @pyqtProperty(bool, notify=changed)
    def hasRepo(self) -> bool:
        return self._has_repo

    @pyqtProperty(str, notify=changed)
    def branch(self) -> str:
        return self._branch

    @pyqtProperty(int, notify=changed)
    def behind(self) -> int:
        return self._behind

    @pyqtProperty(bool, notify=changed)
    def fetching(self) -> bool:
        return self._fetching

    @pyqtProperty(bool, notify=changed)
    def pulling(self) -> bool:
        return self._pulling

    @pyqtProperty(str, notify=nvmrcChanged)
    def nvmrcText(self) -> str:
        return self._nvmrc_text

    @pyqtProperty(bool, notify=nvmrcChanged)
    def nvmrcWarn(self) -> bool:
        return self._nvmrc_warn

    # ── slots ─────────────────────────────────────────────────────────────────

    @pyqtSlot(str)
    def setProject(self, directory: str) -> None:
        self._dir = directory
        self._update_nvmrc()
        if not directory or not self._available:
            self._has_repo = False
            self._branch = ""
            self._behind = 0
            self._fetching = False
            self.changed.emit()
            return
        info = get_git_info(directory)
        if info is None:
            self._has_repo = False
            self._fetching = False
            self.changed.emit()
            return
        self._has_repo = True
        self._branch = info.branch
        self._behind = info.behind
        self._fetching = True
        self.changed.emit()
        self._start_fetch(directory)

    @pyqtSlot(str)
    def setNodeVersion(self, version: str) -> None:
        self._node_version = version
        self._update_nvmrc()

    @pyqtSlot()
    def pull(self) -> None:
        if not self._dir:
            return
        self._pulling = True
        self.changed.emit()
        self._start_pull(self._dir)

    @pyqtSlot()
    def shutdown(self) -> None:
        for thread, _ in list(self._fetch_pairs) + list(self._pull_pairs):
            try:
                if thread.isRunning():
                    thread.quit()
                    thread.wait(2000)
            except RuntimeError:
                pass

    # ── background work ─────────────────────────────────────────────────────────

    def _start_fetch(self, directory: str) -> None:
        worker = _GitFetchWorker(directory)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        worker.finished.connect(lambda d=directory: self._on_fetch_done(d))
        pair = (thread, worker)
        self._fetch_pairs.add(pair)
        thread.finished.connect(lambda _=None, p=pair: self._fetch_pairs.discard(p))
        thread.start()

    def _on_fetch_done(self, directory: str) -> None:
        if directory != self._dir:
            return
        info = get_git_info(directory)
        if info is not None:
            self._has_repo = True
            self._branch = info.branch
            self._behind = info.behind
        self._fetching = False
        self.changed.emit()

    def _start_pull(self, directory: str) -> None:
        worker = _GitPullWorker(directory)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        worker.finished.connect(lambda ok, msg, d=directory: self._on_pull_done(ok, msg, d))
        pair = (thread, worker)
        self._pull_pairs.add(pair)
        thread.finished.connect(lambda _=None, p=pair: self._pull_pairs.discard(p))
        thread.start()

    def _on_pull_done(self, success: bool, message: str, directory: str) -> None:
        self._pulling = False
        if success:
            info = get_git_info(directory)
            if info is not None:
                self._branch = info.branch
                self._behind = info.behind
            self.changed.emit()
            if directory == self._dir:
                self.reloadRequested.emit()
        else:
            self.changed.emit()
            self.pullFailed.emit(message)

    # ── nvmrc ──────────────────────────────────────────────────────────────────

    def _update_nvmrc(self) -> None:
        text, warn = "", False
        if self._dir:
            nvmrc_path = os.path.join(self._dir, ".nvmrc")
            if os.path.isfile(nvmrc_path):
                try:
                    with open(nvmrc_path) as fh:
                        ver = fh.read().strip()
                except Exception:
                    ver = ""
                if ver:
                    text = f".nvmrc: {ver}"
                    if self._node_version:
                        try:
                            node_maj = int(self._node_version.lstrip("v").split(".")[0])
                            nvmrc_maj = int(ver.lstrip("v").split(".")[0])
                            warn = node_maj != nvmrc_maj
                        except (ValueError, IndexError):
                            pass
        if (text, warn) != (self._nvmrc_text, self._nvmrc_warn):
            self._nvmrc_text = text
            self._nvmrc_warn = warn
            self.nvmrcChanged.emit()
