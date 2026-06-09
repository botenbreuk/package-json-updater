"""
Start screen — shown when no package.json is loaded.

Displays recently opened projects with their last-checked dates and
two open buttons (folder or direct file).
"""
from __future__ import annotations

import os
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)


class StartScreen(QWidget):
    """
    Signals
    -------
    file_selected(path)
        Emitted when the user clicks a recent-file row.
    open_folder_requested()
        Emitted when the user clicks "Open Folder".
    open_file_requested()
        Emitted when the user clicks "Open package.json".
    """

    file_selected         = pyqtSignal(str)
    recent_removed        = pyqtSignal(str)   # path
    recents_cleared       = pyqtSignal()
    open_folder_requested = pyqtSignal()
    open_file_requested   = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("startScreen")
        self._build_ui()

    # ── construction ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)

        # Centred column — capped at 540 px so it reads well on wide windows.
        centre = QWidget()
        centre.setMaximumWidth(540)
        clo = QVBoxLayout(centre)
        clo.setContentsMargins(0, 0, 0, 0)
        clo.setSpacing(0)

        # ── logo / headline ───────────────────────────────────────────────────
        icon_lbl = QLabel("📦")
        icon_lbl.setObjectName("startIcon")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        clo.addWidget(icon_lbl)
        clo.addSpacing(14)

        title_lbl = QLabel("Package.json Updater")
        title_lbl.setObjectName("startTitle")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        clo.addWidget(title_lbl)
        clo.addSpacing(6)

        sub_lbl = QLabel("Check and update npm dependencies")
        sub_lbl.setObjectName("startSubtitle")
        sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        clo.addWidget(sub_lbl)
        clo.addSpacing(28)

        # ── open buttons ──────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_folder = QPushButton("📁  Open Folder")
        btn_folder.setObjectName("startBtnSecondary")
        btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_folder.clicked.connect(self.open_folder_requested)

        btn_file = QPushButton("📄  Open package.json")
        btn_file.setObjectName("startBtnPrimary")
        btn_file.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_file.clicked.connect(self.open_file_requested)

        btn_row.addWidget(btn_folder)
        btn_row.addWidget(btn_file)
        clo.addLayout(btn_row)
        clo.addSpacing(36)

        # ── recent files section ──────────────────────────────────────────────
        self._recent_header = QWidget()
        self._recent_header.setVisible(False)
        header_row = QHBoxLayout(self._recent_header)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_lbl = QLabel("RECENT")
        header_lbl.setObjectName("recentHeader")
        header_row.addWidget(header_lbl, 1)
        self._clear_btn = QPushButton("Clear all")
        self._clear_btn.setObjectName("recentClearBtn")
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.clicked.connect(self.recents_cleared)
        header_row.addWidget(self._clear_btn)
        clo.addWidget(self._recent_header)
        clo.addSpacing(8)

        self._rows_widget = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_widget)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(4)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setMinimumHeight(200)
        self._scroll_area.setMaximumHeight(320)
        self._scroll_area.setWidget(self._rows_widget)
        self._scroll_area.setVisible(False)
        clo.addWidget(self._scroll_area)

        self._no_recent_lbl = QLabel("No recent files.")
        self._no_recent_lbl.setObjectName("noRecent")
        self._no_recent_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_recent_lbl.setVisible(False)
        clo.addWidget(self._no_recent_lbl)

        # Horizontal centring
        h = QHBoxLayout()
        h.addStretch(1)
        h.addWidget(centre)
        h.addStretch(1)
        outer.addLayout(h)
        outer.addStretch(1)

    # ── public API ────────────────────────────────────────────────────────────

    def set_recent(self, recent_files: list) -> None:
        """Rebuild the recent-file rows from *recent_files*."""
        # Clear old rows
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        valid = [r for r in recent_files if os.path.isfile(r.get("path", ""))]

        has_any  = bool(recent_files)   # ever had entries
        has_live = bool(valid)          # at least one still exists on disk

        self._recent_header.setVisible(has_any)
        self._scroll_area.setVisible(has_live)
        self._no_recent_lbl.setVisible(has_any and not has_live)

        for entry in valid:
            self._rows_layout.addWidget(self._make_row(entry))
        self._rows_layout.addStretch()

    # ── row builder ───────────────────────────────────────────────────────────

    def _make_row(self, entry: dict) -> QFrame:
        path         = entry["path"]
        last_checked = entry.get("last_checked")

        project_name = os.path.basename(os.path.dirname(path))
        display_path = _shorten_path(path)
        age_text     = _fmt_age(last_checked)

        row = QFrame()
        row.setObjectName("recentRow")
        row.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        h = QHBoxLayout(row)
        h.setContentsMargins(14, 12, 14, 12)
        h.setSpacing(12)

        # Left column: project name + path
        left = QVBoxLayout()
        left.setSpacing(3)

        name_lbl = QLabel(project_name)
        name_lbl.setObjectName("recentName")

        path_lbl = QLabel(display_path)
        path_lbl.setObjectName("recentPath")

        left.addWidget(name_lbl)
        left.addWidget(path_lbl)

        # Right column: last-checked age
        age_lbl = QLabel(age_text)
        age_lbl.setObjectName("recentAge")
        age_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        age_lbl.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)

        remove_btn = QPushButton("×")
        remove_btn.setObjectName("recentRemoveBtn")
        remove_btn.setFixedSize(24, 24)
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setToolTip("Remove from recents")
        remove_btn.clicked.connect(lambda _=False, p=path: self.recent_removed.emit(p))

        h.addLayout(left, 1)
        h.addWidget(age_lbl)
        h.addWidget(remove_btn)

        # Click anywhere on the row (outside the remove button) to open that file
        row.mousePressEvent = lambda _e, p=path: self.file_selected.emit(p)

        return row


# ── module helpers ────────────────────────────────────────────────────────────

def _shorten_path(path: str, max_len: int = 55) -> str:
    home = os.path.expanduser("~")
    if path.startswith(home):
        path = "~" + path[len(home):]
    if len(path) <= max_len:
        return path
    parts = path.split(os.sep)
    if len(parts) > 3:
        return os.sep.join(["…"] + parts[-2:])
    return path


def _fmt_age(iso_str: str | None) -> str:
    if not iso_str:
        return "Never checked"
    try:
        diff  = datetime.now() - datetime.fromisoformat(iso_str)
        days  = diff.days
        hours = diff.seconds // 3600
        mins  = diff.seconds // 60
        if days == 0:
            if mins  == 0: return "Checked just now"
            if hours == 0: return f"Checked {mins}m ago"
            return f"Checked {hours}h ago"
        if days == 1:
            return "Checked yesterday"
        if days < 30:
            return f"Checked {days} days ago"
        months = days // 30
        if days < 365:
            return f"Checked {months}mo ago"
        years = days // 365
        return f"Checked {years}y ago"
    except Exception:
        return "Checked recently"
