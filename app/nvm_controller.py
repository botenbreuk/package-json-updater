"""
Controller that switches the active Node version via nvm.  Exposed to QML as
the ``Nvm`` property.

Two distinct actions are offered in the UI:

* a plain ``nvm use <version>`` — affects only the throwaway shell it runs
  in, so it has no effect this app (or a new terminal) can observe later;
* pinning it as the nvm default (``nvm alias default <version>``), which is
  what actually makes future PATH resolution — this app's own
  ``core/node_env.py``, and any new terminal — pick the version up.

Either one falls back to ``nvm install <version>`` (after the user grants
permission) when the requested version isn't installed yet.

nvm is a shell function, not an executable, so every command below sources
``~/.nvm/nvm.sh`` in a throwaway bash process first — the same install
location ``core/node_env.py`` already reads directly when resolving PATH.
"""
from __future__ import annotations

import os
import shlex

from PyQt6.QtCore import (
    QObject, QProcess, QProcessEnvironment, pyqtProperty, pyqtSignal, pyqtSlot,
)

from core.node_env import node_path_env

_NVM_DIR = os.path.expanduser("~/.nvm")
_NVM_SH = os.path.join(_NVM_DIR, "nvm.sh")
_USE_FAILED_MARKER = "__PJU_NVM_USE_FAILED__"


def _nvm_preamble() -> str:
    return (
        f"export NVM_DIR={shlex.quote(_NVM_DIR)}\n"
        f"[ -s {shlex.quote(_NVM_SH)} ] && . {shlex.quote(_NVM_SH)}\n"
    )


class NvmController(QObject):
    busyChanged = pyqtSignal()
    statusChanged = pyqtSignal()
    notInstalled = pyqtSignal(str)          # version — `nvm use` failed because it's missing
    switched = pyqtSignal(str, bool)        # version, pinnedDefault — action succeeded
    failed = pyqtSignal(str)                # message — unexpected nvm failure

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._busy = False
        self._status_text = ""
        self._output = ""
        self._pending_version = ""
        self._pending_mode = ""        # "use" | "install"
        self._pending_pin_default = False

    @pyqtProperty(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @pyqtProperty(str, notify=statusChanged)
    def statusText(self) -> str:
        return self._status_text

    @pyqtSlot(str, bool)
    def switchTo(self, version: str, pin_default: bool) -> None:
        """Run ``nvm use <version>``, optionally pinning it as the nvm default.

        Emits notInstalled (not a generic failure) if the version isn't
        installed yet, so the caller can ask permission to install it.
        """
        version = version.strip()
        if self._busy or not version:
            return
        if not os.path.isfile(_NVM_SH):
            self.failed.emit(f"nvm was not found at {_NVM_DIR} — is it installed?")
            return
        self._pending_pin_default = pin_default
        script = _nvm_preamble() + (
            f"nvm use {shlex.quote(version)} "
            f"|| {{ echo {shlex.quote(_USE_FAILED_MARKER)}; exit 7; }}\n"
        )
        if pin_default:
            script += f"nvm alias default {shlex.quote(version)}\n"
        status = f"Setting Node {version} as default…" if pin_default else f"Switching to Node {version}…"
        self._start(version, "use", script, status)

    @pyqtSlot(str)
    def install(self, version: str) -> None:
        """``nvm install <version>`` (also activates it) after the user OK'd it.

        Mirrors whichever action requested it: also pins the nvm default
        when the ``switchTo`` call that led here asked for that.
        """
        version = version.strip()
        if self._busy or not version:
            return
        if not os.path.isfile(_NVM_SH):
            self.failed.emit(f"nvm was not found at {_NVM_DIR} — is it installed?")
            return
        script = _nvm_preamble() + f"nvm install {shlex.quote(version)}"
        if self._pending_pin_default:
            script += f" && nvm alias default {shlex.quote(version)}"
        script += "\n"
        self._start(version, "install", script, f"Installing Node {version}…")

    def _start(self, version: str, mode: str, script: str, status_text: str) -> None:
        self._pending_version = version
        self._pending_mode = mode
        self._output = ""
        self._set_busy(True, status_text)

        proc = QProcess(self)
        self._process = proc

        env = node_path_env()
        proc_env = QProcessEnvironment.systemEnvironment()
        proc_env.insert("PATH", env["PATH"])
        proc.setProcessEnvironment(proc_env)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.readyReadStandardOutput.connect(self._on_output)
        proc.finished.connect(self._on_finished)
        proc.start("bash", ["-c", script])

        if not proc.waitForStarted(3000):
            self._set_busy(False)
            self.failed.emit("Could not start a shell to run nvm.")

    def _on_output(self) -> None:
        if self._process is None:
            return
        raw = bytes(self._process.readAllStandardOutput())
        self._output += raw.decode("utf-8", errors="replace")

    def _on_finished(self, exit_code: int, _exit_status) -> None:
        version, mode, output = self._pending_version, self._pending_mode, self._output
        self._set_busy(False)
        if exit_code == 0:
            self.switched.emit(version, self._pending_pin_default)
            return
        if mode == "use" and _USE_FAILED_MARKER in output:
            self.notInstalled.emit(version)
            return
        self.failed.emit(output.strip() or f"nvm exited with code {exit_code}")

    def _set_busy(self, value: bool, text: str = "") -> None:
        self._busy = value
        self._status_text = text
        self.busyChanged.emit()
        self.statusChanged.emit()

    @pyqtSlot()
    def shutdown(self) -> None:
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
            self._process.waitForFinished(2000)
