"""
QTableWidget subclass showing all dependencies.

Each row has:
  • a checkbox for multi-select (Update Selected)
  • group badge, package name, current constraint, constraint-type badge
  • one VersionCellWidget per bump level (Patch / Minor / Major),
    each carrying its own ↑ update button
"""
from __future__ import annotations

import re
from typing import Optional

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QDesktopServices, QFont, QFontDatabase
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QWidget,
)

from models.dependency import DependencyInfo
from .version_cell_widget import VersionCellWidget

# Column indices
COL_SELECT  = 0
COL_GROUP   = 1
COL_PACKAGE = 2
COL_CURRENT = 3
COL_TYPE    = 4   # constraint-type badge
COL_PATCH   = 5
COL_MINOR   = 6
COL_MAJOR   = 7

HEADERS = ["", "Group", "Package", "Current", "Type", "Patch ↑", "Minor ↑", "Major ↑"]
VERSION_COLS = {COL_PATCH: "patch", COL_MINOR: "minor", COL_MAJOR: "major"}

# ── group badge colours ───────────────────────────────────────────────────────

_GROUP_COLORS = {
    "dependencies":    QColor("#dbeafe"),
    "devDependencies": QColor("#f0fdf4"),
    "overrides":       QColor("#fefce8"),
}
_GROUP_TEXT = {
    "dependencies":    QColor("#1d4ed8"),
    "devDependencies": QColor("#15803d"),
    "overrides":       QColor("#92400e"),
}
_GROUP_COLORS_DARK = {
    "dependencies":    QColor("#1e3a5f"),
    "devDependencies": QColor("#14532d"),
    "overrides":       QColor("#451a03"),
}
_GROUP_TEXT_DARK = {
    "dependencies":    QColor("#93c5fd"),
    "devDependencies": QColor("#86efac"),
    "overrides":       QColor("#fcd34d"),
}

# ── constraint-type badge colours ─────────────────────────────────────────────

_TYPE_LABEL = {
    "caret":    "Compatible",
    "tilde":    "Tilde",
    "exact":    "Exact",
    "range":    "Range",
    "wildcard": "Wildcard",
    "any":      "Any",
    "local":    "Local",
}
# (background, foreground) — light theme
_TYPE_COLORS: dict[str, tuple[QColor, QColor]] = {
    "caret":    (QColor("#dbeafe"), QColor("#1d4ed8")),
    "tilde":    (QColor("#dcfce7"), QColor("#15803d")),
    "exact":    (QColor("#f1f5f9"), QColor("#475569")),
    "range":    (QColor("#ffedd5"), QColor("#c2410c")),
    "wildcard": (QColor("#cffafe"), QColor("#0e7490")),
    "any":      (QColor("#ede9fe"), QColor("#6d28d9")),
    "local":    (QColor("#fdf4ff"), QColor("#7e22ce")),
}
# (background, foreground) — dark theme
_TYPE_COLORS_DARK: dict[str, tuple[QColor, QColor]] = {
    "caret":    (QColor("#1e3a5f"), QColor("#93c5fd")),
    "tilde":    (QColor("#14532d"), QColor("#86efac")),
    "exact":    (QColor("#1e293b"), QColor("#94a3b8")),
    "range":    (QColor("#431407"), QColor("#fdba74")),
    "wildcard": (QColor("#164e63"), QColor("#67e8f9")),
    "any":      (QColor("#2e1065"), QColor("#c4b5fd")),
    "local":    (QColor("#3b0764"), QColor("#d8b4fe")),
}

_FALLBACK_LIGHT = (QColor("#f1f5f9"), QColor("#475569"))
_FALLBACK_DARK  = (QColor("#1e293b"), QColor("#94a3b8"))


def _fmt_age_warn(days: int) -> str:
    years, rem = divmod(days, 365)
    months = rem // 30
    if years and months:
        age = f"{years} year{'s' if years != 1 else ''} {months} month{'s' if months != 1 else ''}"
    elif years:
        age = f"{years} year{'s' if years != 1 else ''}"
    else:
        age = f"{months or 1} month{'s' if months != 1 else ''}"
    return f"Installed version is {age} old — consider updating"


def _repo_label(url: str) -> str:
    """Return a short platform label for *url*, e.g. 'GitHub', 'GitLab', 'repo'."""
    u = url.lower()
    if "github.com" in u:
        return "GitHub ↗"
    if "gitlab.com" in u:
        return "GitLab ↗"
    if "bitbucket.org" in u:
        return "Bitbucket ↗"
    return "repo ↗"


def _constraint_type(raw: str) -> str:
    """Return the constraint-type key for *raw* (the string in package.json)."""
    s = raw.strip()
    if not s or s == "*":
        return "any"
    if s.startswith(("workspace:", "file:", "link:", "npm:", "git+", "github:")):
        return "local"
    if s.startswith("^"):
        return "caret"
    if s.startswith("~"):
        return "tilde"
    if re.search(r"[<>=]", s):
        return "range"
    if re.search(r"[xX]|\.\*", s):
        return "wildcard"
    return "exact"


class DependencyTable(QTableWidget):
    """
    Signals
    -------
    update_requested(dep, new_version)
        Emitted when the user clicks a ↑ button inside a version cell.
    selection_changed()
        Emitted whenever a row checkbox is toggled.
    """

    update_requested = pyqtSignal(object, str)
    selection_changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(HEADERS), parent)
        self._deps: list[DependencyInfo] = []
        self._row_map: dict[tuple, int] = {}   # dep.row_key → row index
        self._filter_group: Optional[str] = None
        self._hide_uptodate: bool = False
        self._filter_old_only: bool = False
        self._merge_patch_minor: bool = False
        self._dark: bool = False
        self._old_age_threshold_days: int = 0

        self._setup_table()

        self._empty_lbl = QLabel("All packages are up to date", self.viewport())
        self._empty_lbl.setObjectName("tableEmptyMsg")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._empty_lbl.hide()

        hh = self.horizontalHeader()
        self._header_checkbox = QPushButton(hh.viewport())
        self._header_checkbox.setObjectName("tableCheckbox")
        self._header_checkbox.setCheckable(True)
        self._header_checkbox.setFixedSize(20, 20)
        self._header_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header_checkbox.setToolTip("Select / deselect all")
        self._header_checkbox.toggled.connect(self._on_header_checkbox_toggled)
        hh.sectionResized.connect(lambda *_: self._reposition_header_checkbox())
        self._reposition_header_checkbox()

    # ── setup ────────────────────────────────────────────────────────────────

    def _setup_table(self) -> None:
        self.setHorizontalHeaderLabels(HEADERS)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)

        hh = self.horizontalHeader()
        hh.setSectionResizeMode(COL_SELECT,  QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(COL_GROUP,   QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(COL_PACKAGE, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(COL_CURRENT, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(COL_TYPE,    QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(COL_PATCH,   QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(COL_MINOR,   QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(COL_MAJOR,   QHeaderView.ResizeMode.Fixed)

        self.setColumnWidth(COL_SELECT,  52)
        self.setColumnWidth(COL_GROUP,   74)
        self.setColumnWidth(COL_CURRENT, 150)
        self.setColumnWidth(COL_TYPE,    110)
        self.setColumnWidth(COL_PATCH,   150)
        self.setColumnWidth(COL_MINOR,   150)
        self.setColumnWidth(COL_MAJOR,   150)

        self.verticalHeader().setDefaultSectionSize(40)

    # ── public API ───────────────────────────────────────────────────────────

    def populate(self, deps: list[DependencyInfo]) -> None:
        """Build the table from scratch."""
        self.setUpdatesEnabled(False)
        try:
            self.set_header_check_state(False)
            self._deps = deps
            self._row_map = {}
            self.setRowCount(0)
            for dep in deps:
                self._add_row(dep)
            self._apply_filters()
        finally:
            self.setUpdatesEnabled(True)

    def update_row(self, dep: DependencyInfo) -> None:
        """Refresh the Current cell, Type badge, and version cells for *dep*."""
        row = self._row_map.get(dep.row_key)
        if row is None:
            return
        self._refresh_current_cell(row, dep)
        self._refresh_package_cell(row, dep)
        self._update_type_badge(row, dep)
        self._refresh_version_cells(row, dep)
        self._apply_filter_to_row(row, dep)
        self._update_empty_label()

    def set_filter_group(self, group: Optional[str]) -> None:
        self._filter_group = group
        self._apply_filters()

    def set_hide_uptodate(self, hide: bool) -> None:
        self._hide_uptodate = hide
        self._apply_filters()

    def set_filter_old_only(self, old_only: bool) -> None:
        self._filter_old_only = old_only
        self._apply_filters()

    def set_old_age_threshold(self, days: int) -> None:
        if self._old_age_threshold_days == days:
            return
        self._old_age_threshold_days = days
        for dep in self._deps:
            row = self._row_map.get(dep.row_key)
            if row is not None:
                self._refresh_current_cell(row, dep)

    def get_selected_deps(self) -> list[DependencyInfo]:
        """Return all deps whose checkbox is checked."""
        result = []
        for dep in self._deps:
            row = self._row_map.get(dep.row_key)
            if row is None:
                continue
            cb = self._row_checkbox(row)
            if cb and cb.isChecked():
                result.append(dep)
        return result

    def _row_checkbox(self, row: int) -> QPushButton | None:
        container = self.cellWidget(row, COL_SELECT)
        if container is None:
            return None
        return container.findChild(QPushButton)

    def get_all_deps(self) -> list[DependencyInfo]:
        return list(self._deps)

    def set_checkboxes_enabled(self, enabled: bool) -> None:
        """Enable or disable row checkboxes; when enabling, up-to-date deps stay disabled."""
        for dep in self._deps:
            row = self._row_map.get(dep.row_key)
            if row is None:
                continue
            cb = self._row_checkbox(row)
            if cb:
                if enabled:
                    can_select = dep.has_any_update or dep.needs_install or dep.fetch_status != "done"
                    cb.setEnabled(can_select)
                    if not can_select and cb.isChecked():
                        cb.setChecked(False)
                else:
                    cb.setEnabled(False)

    def select_all(self, checked: bool) -> None:
        """Check or uncheck all visible, enabled row checkboxes."""
        for dep in self._deps:
            row = self._row_map.get(dep.row_key)
            if row is None or self.isRowHidden(row):
                continue
            cb = self._row_checkbox(row)
            if cb and cb.isEnabled():
                cb.blockSignals(True)
                cb.setChecked(checked)
                cb.blockSignals(False)
        self.selection_changed.emit()

    def set_header_check_state(self, checked: bool) -> None:
        self._header_checkbox.blockSignals(True)
        self._header_checkbox.setChecked(checked)
        self._header_checkbox.blockSignals(False)

    def _on_header_checkbox_toggled(self, checked: bool) -> None:
        self.select_all(checked)

    def _reposition_header_checkbox(self) -> None:
        hh = self.horizontalHeader()
        x0 = hh.sectionViewportPosition(COL_SELECT)
        w = hh.sectionSize(COL_SELECT)
        h = hh.height()
        cb = self._header_checkbox
        cb.move(x0 + (w - cb.width()) // 2, max(0, (h - cb.height()) // 2))

    def get_selectable_count(self) -> int:
        """Return number of visible, enabled checkboxes."""
        count = 0
        for dep in self._deps:
            row = self._row_map.get(dep.row_key)
            if row is None or self.isRowHidden(row):
                continue
            cb = self._row_checkbox(row)
            if cb and cb.isEnabled():
                count += 1
        return count

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._empty_lbl.isVisible():
            self._empty_lbl.setGeometry(self.viewport().rect())
        self._reposition_header_checkbox()

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        for dep in self._deps:
            row = self._row_map.get(dep.row_key)
            if row is not None:
                self._update_group_badge(row, dep)
                self._update_type_badge(row, dep)
        self.viewport().update()

    def set_merge_patch_minor(self, merge: bool) -> None:
        if self._merge_patch_minor == merge:
            return
        self._merge_patch_minor = merge
        self.setColumnHidden(COL_PATCH, merge)
        header_item = self.horizontalHeaderItem(COL_MINOR)
        if header_item:
            header_item.setText("Minor / Patch ↑" if merge else "Minor ↑")
        for dep in self._deps:
            row = self._row_map.get(dep.row_key)
            if row is not None:
                self._refresh_version_cells(row, dep)

    # ── internal row management ──────────────────────────────────────────────

    def _add_row(self, dep: DependencyInfo) -> None:
        row = self.rowCount()
        self.insertRow(row)
        self._row_map[dep.row_key] = row

        # ── checkbox ──────────────────────────────────────────────────────────
        chk_container = QWidget()
        chk_container.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        chk_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        chk_layout = QHBoxLayout(chk_container)
        chk_layout.setContentsMargins(0, 0, 0, 0)
        chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chk = QPushButton()
        chk.setObjectName("tableCheckbox")
        chk.setCheckable(True)
        chk.setFixedSize(20, 20)
        chk.setCursor(Qt.CursorShape.PointingHandCursor)
        chk.toggled.connect(lambda _: self.selection_changed.emit())
        chk_layout.addWidget(chk)
        self.setCellWidget(row, COL_SELECT, chk_container)

        # ── group badge ───────────────────────────────────────────────────────
        badge_font = QFont()
        badge_font.setPointSize(11)
        badge_font.setBold(True)
        group_item = QTableWidgetItem(dep.group_label)
        group_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        group_item.setFont(badge_font)
        self.setItem(row, COL_GROUP, group_item)
        self._update_group_badge(row, dep)

        # ── package name ──────────────────────────────────────────────────────
        self._refresh_package_cell(row, dep)

        # ── current constraint ────────────────────────────────────────────────
        self._refresh_current_cell(row, dep)

        # ── constraint-type badge ─────────────────────────────────────────────
        type_font = QFont()
        type_font.setPointSize(11)
        type_font.setBold(True)
        type_item = QTableWidgetItem()
        type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        type_item.setFont(type_font)
        self.setItem(row, COL_TYPE, type_item)
        self._update_type_badge(row, dep)

        # ── version cells (initially loading) ────────────────────────────────
        self._refresh_version_cells(row, dep)

    def _refresh_current_cell(self, row: int, dep: DependencyInfo) -> None:
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(14)

        container = QWidget()
        container.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(6)
        layout.addStretch()

        cur_lbl = QLabel(dep.raw_constraint)
        cur_lbl.setFont(mono)
        cur_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cur_lbl.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        cur_lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout.addWidget(cur_lbl)

        if dep.needs_install:
            chip = QLabel("pending")
            chip.setObjectName("pkgPendingChip")
            layout.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)

        if (
            dep.current_age is not None
            and self._old_age_threshold_days > 0
            and dep.current_age >= self._old_age_threshold_days
        ):
            warn_lbl = QLabel("⚠")
            warn_lbl.setObjectName("currentVersionWarn")
            warn_lbl.setToolTip(_fmt_age_warn(dep.current_age))
            layout.addWidget(warn_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        layout.addStretch()
        self.setCellWidget(row, COL_CURRENT, container)

    def _refresh_package_cell(self, row: int, dep: DependencyInfo) -> None:
        """Build (or rebuild) the package-name cell widget."""
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(14)

        container = QWidget()
        container.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(6)

        name_lbl = QLabel(dep.name)
        name_lbl.setFont(mono)
        name_lbl.setObjectName("pkgName")
        name_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(name_lbl)
        if dep.override_parent is not None:
            parent_lbl = QLabel(f"in {dep.override_parent}")
            parent_lbl.setObjectName("pkgParentHint")
            parent_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(parent_lbl)
        layout.addStretch(1)

        npm_url = f"https://www.npmjs.com/package/{dep.name}"
        npm_btn = QPushButton("npm ↗")
        npm_btn.setObjectName("pkgLinkBtn")
        npm_btn.setFixedHeight(24)
        npm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        npm_btn.setToolTip(npm_url)
        npm_btn.clicked.connect(lambda _=False, u=npm_url: QDesktopServices.openUrl(QUrl(u)))
        layout.addWidget(npm_btn)

        if dep.repo_url:
            repo_btn = QPushButton(_repo_label(dep.repo_url))
            repo_btn.setObjectName("pkgLinkBtn")
            repo_btn.setFixedHeight(24)
            repo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            repo_btn.setToolTip(dep.repo_url)
            url = dep.repo_url
            repo_btn.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            layout.addWidget(repo_btn)

        self.setCellWidget(row, COL_PACKAGE, container)

    def _update_group_badge(self, row: int, dep: DependencyInfo) -> None:
        item = self.item(row, COL_GROUP)
        if not item:
            return
        if self._dark:
            bg = _GROUP_COLORS_DARK.get(dep.group, QColor("#1e293b"))
            fg = _GROUP_TEXT_DARK.get(dep.group, QColor("#94a3b8"))
        else:
            bg = _GROUP_COLORS.get(dep.group, QColor("#e5e7eb"))
            fg = _GROUP_TEXT.get(dep.group, QColor("#374151"))
        item.setBackground(QBrush(bg))
        item.setForeground(QBrush(fg))

    def _update_type_badge(self, row: int, dep: DependencyInfo) -> None:
        item = self.item(row, COL_TYPE)
        if not item:
            return
        key = _constraint_type(dep.raw_constraint)
        item.setText(_TYPE_LABEL.get(key, key.capitalize()))
        if self._dark:
            bg, fg = _TYPE_COLORS_DARK.get(key, _FALLBACK_DARK)
        else:
            bg, fg = _TYPE_COLORS.get(key, _FALLBACK_LIGHT)
        item.setBackground(QBrush(bg))
        item.setForeground(QBrush(fg))

    def _refresh_version_cells(self, row: int, dep: DependencyInfo) -> None:
        """Replace all three version cell widgets for *row*."""
        if dep.fetch_status == "loading" and self.cellWidget(row, COL_PATCH) is not None:
            # Re-fetch: keep existing widgets visible but disabled
            for col in (COL_PATCH, COL_MINOR, COL_MAJOR):
                w = self.cellWidget(row, col)
                if w is not None:
                    w.setEnabled(False)
            return

        if self._merge_patch_minor:
            if dep.latest_minor:
                merged_v, merged_age, merged_bump = dep.latest_minor, dep.minor_age, "minor"
            elif dep.latest_patch:
                merged_v, merged_age, merged_bump = dep.latest_patch, dep.patch_age, "patch"
            else:
                merged_v, merged_age, merged_bump = None, None, "minor"
            minor_entry = (merged_v, merged_age, merged_bump)
        else:
            minor_entry = (dep.latest_minor, dep.minor_age, "minor")

        versions = {
            COL_PATCH: (dep.latest_patch, dep.patch_age, "patch"),
            COL_MINOR: minor_entry,
            COL_MAJOR: (dep.latest_major, dep.major_age, "major"),
        }
        for col, (version, age, bump_type) in versions.items():
            if dep.fetch_status == "loading":
                status = "loading"
                v = None
                age = None
            elif dep.fetch_status == "error":
                status = "error"
                v = None
                age = None
            else:
                status = "ok" if version else "none"
                v = version

            widget = VersionCellWidget(
                dep=dep,
                version=v,
                age_days=age,
                bump_type=bump_type,
                status=status,
                error_msg=dep.error_message if dep.fetch_status == "error" else "",
            )
            widget.update_clicked.connect(self.update_requested)
            self.setCellWidget(row, col, widget)

    # ── filtering ────────────────────────────────────────────────────────────

    def _apply_filters(self) -> None:
        for dep in self._deps:
            row = self._row_map.get(dep.row_key)
            if row is not None:
                self._apply_filter_to_row(row, dep)
        self._update_empty_label()

    def _apply_filter_to_row(self, row: int, dep: DependencyInfo) -> None:
        hidden = False
        if self._filter_group and dep.group != self._filter_group:
            hidden = True
        if self._hide_uptodate:
            if dep.fetch_status == "loading":
                hidden = hidden or self.isRowHidden(row)
            elif not dep.has_any_update and dep.fetch_status == "done" and not dep.needs_install:
                hidden = True
        if self._filter_old_only:
            is_old = (
                dep.current_age is not None
                and self._old_age_threshold_days > 0
                and dep.current_age >= self._old_age_threshold_days
            )
            if dep.fetch_status == "loading":
                hidden = hidden or self.isRowHidden(row)
            elif not is_old:
                hidden = True
        self.setRowHidden(row, hidden)

    def _update_empty_label(self) -> None:
        any_visible = any(
            not self.isRowHidden(self._row_map[dep.row_key])
            for dep in self._deps
            if dep.row_key in self._row_map
        )
        show = bool(self._deps) and not any_visible
        self._empty_lbl.setVisible(show)
        if show:
            self._empty_lbl.setGeometry(self.viewport().rect())
