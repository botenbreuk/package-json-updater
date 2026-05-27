"""
Inline version cell widget: version text + release-age + bump button.

States
------
loading  — italic "Loading…", no button
error    — red "Error", no button (tooltip carries the message)
none     — dim "—", no button (dep is already up to date for this level)
ok       — version + age sub-text + coloured ↑ button
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from models.dependency import DependencyInfo


def _fmt_age(days: int | None) -> str:
    if days is None:
        return ""
    if days < 1:
        return "today"
    if days < 30:
        return f"{days}d"
    if days < 365:
        return f"{days // 30}mo"
    return f"{days // 365}y"


class VersionCellWidget(QWidget):
    """
    Signals
    -------
    update_clicked(dep, new_version)
        Emitted when the user clicks the ↑ button.
    """

    update_clicked = pyqtSignal(object, str)  # dep, new_version

    def __init__(
        self,
        dep: DependencyInfo,
        version: str | None,
        age_days: int | None,
        bump_type: str | None,   # 'patch' | 'minor' | 'major' | None
        status: str,             # 'loading' | 'error' | 'none' | 'ok'
        error_msg: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._dep = dep
        self._version = version
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._build(version, age_days, bump_type, status, error_msg)

    # ── construction ─────────────────────────────────────────────────────────

    def _build(
        self,
        version: str | None,
        age_days: int | None,
        bump_type: str | None,
        status: str,
        error_msg: str,
    ) -> None:
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 0, 8, 0)
        h.setSpacing(6)

        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(13)

        if status == "loading":
            lbl = QLabel("Loading…")
            lbl.setObjectName("vcwLoading")
            h.addWidget(lbl)
            h.addStretch()

        elif status == "error":
            lbl = QLabel("Error")
            lbl.setObjectName("vcwError")
            if error_msg:
                lbl.setToolTip(error_msg)
            h.addWidget(lbl)
            h.addStretch()

        elif not version:
            lbl = QLabel("—")
            lbl.setObjectName("vcwNone")
            h.addWidget(lbl)
            h.addStretch()

        else:
            # Left: version text + age sub-text
            info = QVBoxLayout()
            info.setSpacing(1)
            info.setContentsMargins(0, 0, 0, 0)

            ver_lbl = QLabel(version)
            ver_lbl.setFont(mono)
            ver_lbl.setObjectName("vcwVersion")
            info.addWidget(ver_lbl)

            age_text = _fmt_age(age_days)
            if age_text:
                age_lbl = QLabel(age_text)
                age_lbl.setObjectName("vcwAge")
                info.addWidget(age_lbl)

            h.addLayout(info, 1)

            # Right: bump button
            obj_name = (
                f"vcwBtn{bump_type.capitalize()}" if bump_type else "vcwBtnPatch"
            )
            btn = QPushButton("↑")
            btn.setObjectName(obj_name)
            btn.setFixedSize(24, 24)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"Update to {version}")
            # Capture by value to avoid late-binding closure issues
            btn.clicked.connect(
                lambda _checked=False, d=self._dep, v=version:
                self.update_clicked.emit(d, v)
            )
            h.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
