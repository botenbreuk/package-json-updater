"""
QTableWidget subclass for Maven pom.xml dependencies.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QFontDatabase
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from models.maven_dependency import MavenDependencyInfo

COL_SELECT   = 0
COL_SCOPE    = 1
COL_ARTIFACT = 2
COL_CURRENT  = 3
COL_LATEST   = 4

HEADERS = ["", "Scope", "Artifact", "Current", "Latest"]

_SCOPE_LIGHT: dict[str, tuple[QColor, QColor]] = {
    "compile":  (QColor("#dbeafe"), QColor("#1d4ed8")),
    "test":     (QColor("#dcfce7"), QColor("#15803d")),
    "provided": (QColor("#fefce8"), QColor("#92400e")),
    "runtime":  (QColor("#ede9fe"), QColor("#6d28d9")),
}
_SCOPE_DARK: dict[str, tuple[QColor, QColor]] = {
    "compile":  (QColor("#1e3a5f"), QColor("#93c5fd")),
    "test":     (QColor("#14532d"), QColor("#86efac")),
    "provided": (QColor("#451a03"), QColor("#fcd34d")),
    "runtime":  (QColor("#2e1065"), QColor("#c4b5fd")),
}
_SCOPE_FALLBACK_LIGHT = (QColor("#f1f5f9"), QColor("#475569"))
_SCOPE_FALLBACK_DARK  = (QColor("#1e293b"), QColor("#94a3b8"))


class _LatestCellWidget(QWidget):
    """Shows loading / error / up-to-date / update-available states."""

    update_clicked = pyqtSignal(object, str)  # dep, new_version

    def __init__(self, dep: MavenDependencyInfo, parent=None) -> None:
        super().__init__(parent)
        self._dep = dep
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._build()

    def _build(self) -> None:
        dep = self._dep
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 8, 0)
        layout.setSpacing(6)

        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(13)

        if dep.is_managed:
            lbl = QLabel("—")
            lbl.setObjectName("vcwNone")
            layout.addWidget(lbl)
            layout.addStretch()
            return

        if dep.fetch_status == "loading":
            lbl = QLabel("Loading…")
            lbl.setObjectName("vcwLoading")
            layout.addWidget(lbl)
            layout.addStretch()
            return

        if dep.fetch_status == "error":
            lbl = QLabel("Error")
            lbl.setObjectName("vcwError")
            if dep.error_message:
                lbl.setToolTip(dep.error_message)
            layout.addWidget(lbl)
            layout.addStretch()
            return

        if not dep.has_update:
            lbl = QLabel("—")
            lbl.setObjectName("vcwNone")
            layout.addWidget(lbl)
            layout.addStretch()
            return

        # Has update
        ver_lbl = QLabel(dep.latest_version)
        ver_lbl.setFont(mono)
        ver_lbl.setObjectName("vcwVersion")
        layout.addWidget(ver_lbl, 1)

        btn = QPushButton("↑")
        btn.setObjectName("vcwBtnMinor")
        btn.setFixedSize(28, 28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(f"Update to {dep.latest_version}")
        v = dep.latest_version
        btn.clicked.connect(lambda _=False, d=self._dep, nv=v: self.update_clicked.emit(d, nv))
        layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)


class MavenDependencyTable(QTableWidget):
    update_requested = pyqtSignal(object, str)   # dep, new_version
    selection_changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(HEADERS), parent)
        self._deps: list[MavenDependencyInfo] = []
        self._dep_map: dict[str, int] = {}   # coordinate → row
        self._hide_uptodate = False
        self._dark = False
        self._setup()

        self._empty_lbl = QLabel("All dependencies are up to date", self.viewport())
        self._empty_lbl.setObjectName("tableEmptyMsg")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._empty_lbl.hide()

    def _setup(self) -> None:
        self.setHorizontalHeaderLabels(HEADERS)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)

        hh = self.horizontalHeader()
        hh.setSectionResizeMode(COL_SELECT,   QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(COL_SCOPE,    QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(COL_ARTIFACT, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(COL_CURRENT,  QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(COL_LATEST,   QHeaderView.ResizeMode.Fixed)

        self.setColumnWidth(COL_SELECT,  44)
        self.setColumnWidth(COL_SCOPE,   80)
        self.setColumnWidth(COL_CURRENT, 150)
        self.setColumnWidth(COL_LATEST,  180)

        self.verticalHeader().setDefaultSectionSize(58)

    # ── resize: keep empty label filling viewport ─────────────────────────────

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._empty_lbl.isVisible():
            self._empty_lbl.setGeometry(self.viewport().rect())

    # ── public API ────────────────────────────────────────────────────────────

    def populate(self, deps: list[MavenDependencyInfo]) -> None:
        self._deps = deps
        self._dep_map = {}
        self.setRowCount(0)
        for dep in deps:
            self._add_row(dep)
        self._apply_filters()

    def update_row(self, dep: MavenDependencyInfo) -> None:
        row = self._dep_map.get(dep.coordinate)
        if row is None:
            return
        self._refresh_artifact_cell(row, dep)
        self._refresh_current_cell(row, dep)
        self._refresh_latest_cell(row, dep)
        self._apply_filter_to_row(row, dep)
        self._update_empty_label()

    def set_hide_uptodate(self, hide: bool) -> None:
        self._hide_uptodate = hide
        self._apply_filters()

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        for dep in self._deps:
            row = self._dep_map.get(dep.coordinate)
            if row is not None:
                self._refresh_scope_badge(row, dep)
        self.viewport().update()

    def get_selected_deps(self) -> list[MavenDependencyInfo]:
        result = []
        for dep in self._deps:
            row = self._dep_map.get(dep.coordinate)
            if row is None:
                continue
            cb = self._row_checkbox(row)
            if cb and cb.isChecked():
                result.append(dep)
        return result

    def set_checkboxes_enabled(self, enabled: bool) -> None:
        for dep in self._deps:
            row = self._dep_map.get(dep.coordinate)
            if row is None:
                continue
            cb = self._row_checkbox(row)
            if cb:
                cb.setEnabled(enabled)

    # ── internal ──────────────────────────────────────────────────────────────

    def _row_checkbox(self, row: int) -> Optional[QPushButton]:
        container = self.cellWidget(row, COL_SELECT)
        return container.findChild(QPushButton) if container else None

    def _add_row(self, dep: MavenDependencyInfo) -> None:
        row = self.rowCount()
        self.insertRow(row)
        self._dep_map[dep.coordinate] = row

        # Checkbox
        chk_cont = QWidget()
        chk_cont.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        chk_cont.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        chk_layout = QHBoxLayout(chk_cont)
        chk_layout.setContentsMargins(0, 0, 0, 0)
        chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chk = QPushButton()
        chk.setObjectName("tableCheckbox")
        chk.setCheckable(True)
        chk.setFixedSize(20, 20)
        chk.setCursor(Qt.CursorShape.PointingHandCursor)
        chk.toggled.connect(lambda _: self.selection_changed.emit())
        chk_layout.addWidget(chk)
        self.setCellWidget(row, COL_SELECT, chk_cont)

        # Scope badge
        badge_font = QFont()
        badge_font.setPointSize(11)
        badge_font.setBold(True)
        scope_item = QTableWidgetItem(dep.scope)
        scope_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        scope_item.setFont(badge_font)
        self.setItem(row, COL_SCOPE, scope_item)
        self._refresh_scope_badge(row, dep)

        # Artifact cell (two-line widget)
        self._refresh_artifact_cell(row, dep)

        # Current version
        self._refresh_current_cell(row, dep)

        # Latest version cell
        self._refresh_latest_cell(row, dep)

    def _refresh_scope_badge(self, row: int, dep: MavenDependencyInfo) -> None:
        item = self.item(row, COL_SCOPE)
        if not item:
            return
        palette = _SCOPE_DARK if self._dark else _SCOPE_LIGHT
        fallback = _SCOPE_FALLBACK_DARK if self._dark else _SCOPE_FALLBACK_LIGHT
        bg, fg = palette.get(dep.scope, fallback)
        item.setBackground(QBrush(bg))
        item.setForeground(QBrush(fg))

    def _refresh_artifact_cell(self, row: int, dep: MavenDependencyInfo) -> None:
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(13)

        container = QWidget()
        container.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(container)
        outer.setContentsMargins(10, 4, 6, 4)
        outer.setSpacing(2)

        # Artifact ID row: name + optional pending chip
        artifact_row = QHBoxLayout()
        artifact_row.setContentsMargins(0, 0, 0, 0)
        artifact_row.setSpacing(6)

        artifact_lbl = QLabel(dep.artifact_id)
        artifact_lbl.setFont(mono)
        artifact_lbl.setObjectName("mvnArtifactId")
        artifact_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        artifact_row.addWidget(artifact_lbl)

        if dep.needs_install:
            chip = QLabel("pending resolve")
            chip.setObjectName("pkgPendingChip")
            artifact_row.addWidget(chip)

        artifact_row.addStretch()
        outer.addLayout(artifact_row)

        group_lbl = QLabel(dep.group_id)
        group_lbl.setObjectName("mvnGroupId")
        group_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(group_lbl)

        self.setCellWidget(row, COL_ARTIFACT, container)

    def _refresh_current_cell(self, row: int, dep: MavenDependencyInfo) -> None:
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(13)

        if dep.is_managed:
            lbl = QLabel("managed")
            lbl.setObjectName("mvnManaged")
        else:
            lbl = QLabel(dep.version or "")
            lbl.setFont(mono)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCellWidget(row, COL_CURRENT, lbl)

    def _refresh_latest_cell(self, row: int, dep: MavenDependencyInfo) -> None:
        widget = _LatestCellWidget(dep)
        widget.update_clicked.connect(self.update_requested)
        self.setCellWidget(row, COL_LATEST, widget)

    # ── filtering ─────────────────────────────────────────────────────────────

    def _apply_filters(self) -> None:
        for dep in self._deps:
            row = self._dep_map.get(dep.coordinate)
            if row is not None:
                self._apply_filter_to_row(row, dep)
        self._update_empty_label()

    def _apply_filter_to_row(self, row: int, dep: MavenDependencyInfo) -> None:
        hidden = False
        if self._hide_uptodate and not dep.has_update and dep.fetch_status == "done":
            hidden = True
        self.setRowHidden(row, hidden)

    def _update_empty_label(self) -> None:
        any_visible = any(
            not self.isRowHidden(self._dep_map[dep.coordinate])
            for dep in self._deps
            if dep.coordinate in self._dep_map
        )
        show = bool(self._deps) and not any_visible
        self._empty_lbl.setVisible(show)
        if show:
            self._empty_lbl.setGeometry(self.viewport().rect())
