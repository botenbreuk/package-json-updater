"""
In-app overlay modal that runs `mvn dependency:resolve` in the project directory and
streams the output live.
"""
from __future__ import annotations

import re
import sys

from PyQt6.QtCore import QEvent, QProcess, QProcessEnvironment, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontDatabase, QPainter, QTextCursor
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][AB012]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class MvnInstallDialog(QWidget):
    succeeded = pyqtSignal()

    def __init__(self, project_dir: str, parent=None) -> None:
        super().__init__(parent)
        self._project_dir = project_dir
        self._process: QProcess | None = None

        if parent:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)

        self._build_ui()
        self._start()
        self.raise_()
        self.show()

    def eventFilter(self, obj, event):  # type: ignore[override]
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
        return super().eventFilter(obj, event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 140))

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 48, 0, 48)
        outer.setSpacing(0)

        card = QFrame()
        card.setObjectName("npmCard")
        card.setFixedWidth(720)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.setSpacing(12)

        title = QLabel("mvn dependency:resolve")
        title.setObjectName("npmCardTitle")
        card_layout.addWidget(title)

        self._progress = QProgressBar()
        self._progress.setObjectName("npmProgress")
        self._progress.setRange(0, 0)
        self._progress.setMaximumHeight(6)
        self._progress.setTextVisible(False)
        card_layout.addWidget(self._progress)

        self._status_lbl = QLabel("Running mvn dependency:resolve…")
        self._status_lbl.setObjectName("npmStatusRunning")
        card_layout.addWidget(self._status_lbl)

        self._toggle_btn = QPushButton("▶   Output")
        self._toggle_btn.setObjectName("npmToggle")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(False)
        self._toggle_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.toggled.connect(self._on_toggle)
        card_layout.addWidget(self._toggle_btn)

        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(12)
        self._output = QTextEdit()
        self._output.setObjectName("npmOutput")
        self._output.setReadOnly(True)
        self._output.setFont(mono)
        self._output.setMinimumHeight(220)
        self._output.setMaximumHeight(380)
        self._output.setVisible(False)
        card_layout.addWidget(self._output)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._close_btn = QPushButton("Close")
        self._close_btn.setObjectName("btnBlue")
        self._close_btn.setMinimumWidth(88)
        self._close_btn.setEnabled(False)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.clicked.connect(self._close)
        btn_row.addWidget(self._close_btn)
        card_layout.addLayout(btn_row)

        outer.addStretch(1)
        outer.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)

    def _close(self) -> None:
        if self.parent():
            self.parent().removeEventFilter(self)
        self.hide()
        self.deleteLater()

    def _start(self) -> None:
        self._process = QProcess(self)
        self._process.setWorkingDirectory(self._project_dir)

        proc_env = QProcessEnvironment.systemEnvironment()
        path = proc_env.value("PATH", "")
        extra = "/usr/local/bin:/opt/homebrew/bin:/opt/homebrew/sbin"
        proc_env.insert("PATH", f"{extra}:{path}")
        self._process.setProcessEnvironment(proc_env)

        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._on_output)
        self._process.finished.connect(self._on_finished)

        if sys.platform == "win32":
            self._process.start("cmd.exe", ["/c", "mvn", "dependency:resolve"])
        else:
            self._process.start("mvn", ["dependency:resolve"])

        if not self._process.waitForStarted(3000):
            self._on_failed_to_start()

    def _on_output(self) -> None:
        raw = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        text = _strip_ansi(raw)
        cur = self._output.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        cur.insertText(text)
        self._output.setTextCursor(cur)
        self._output.ensureCursorVisible()

    def _on_finished(self, exit_code: int, _exit_status) -> None:
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._close_btn.setEnabled(True)

        if exit_code == 0:
            self._status_lbl.setObjectName("npmStatusOk")
            self._status_lbl.setText("✓   Done — dependencies resolved successfully")
            self.succeeded.emit()
        else:
            self._status_lbl.setObjectName("npmStatusError")
            self._status_lbl.setText(f"✕   Failed (exit code {exit_code})")
            self._toggle_btn.setChecked(True)

        self._status_lbl.style().unpolish(self._status_lbl)
        self._status_lbl.style().polish(self._status_lbl)

    def _on_failed_to_start(self) -> None:
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._status_lbl.setObjectName("npmStatusError")
        self._status_lbl.setText("✕   Could not start mvn — is it installed and on PATH?")
        self._status_lbl.style().unpolish(self._status_lbl)
        self._status_lbl.style().polish(self._status_lbl)
        self._close_btn.setEnabled(True)

    def _on_toggle(self, checked: bool) -> None:
        self._output.setVisible(checked)
        self._toggle_btn.setText("▼   Output" if checked else "▶   Output")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
            self._process.waitForFinished(2000)
        super().closeEvent(event)
