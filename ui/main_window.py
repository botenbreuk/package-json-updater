"""
Main application window — wires everything together.
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional

# Absolute, normalised paths to SVG assets — avoids working-directory sensitivity.
# Qt stylesheet url() always wants forward slashes even on Windows.
def _asset(name: str) -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", name)
    ).replace("\\", "/")

_CHECK_ICON    = _asset("check-white.svg")
_CB_UNCHECKED_L = _asset("cb-unchecked-light.svg")
_CB_UNCHECKED_D = _asset("cb-unchecked-dark.svg")
_CB_CHECKED     = _asset("cb-checked.svg")

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QKeySequence, QPalette
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
    QSizePolicy, QStackedWidget, QToolBar, QVBoxLayout, QWidget,
)

from core.node_env import node_path_env
from core.npm_cache import NpmCache
from core.package_json import load as load_package, save as save_package
from models.dependency import DependencyInfo
from models.settings import AppSettings
from workers.fetch_worker import FetchWorker
from .dependency_table import DependencyTable
from .npm_install_dialog import NpmInstallDialog
from .settings_page import SettingsPage
from .start_screen import StartScreen

_UPDATE_MODES = [
    ("Patch & Minor only", "patch_minor"),
    ("All (including Major)", "all"),
]


class _ElidingLabel(QLabel):
    """QLabel that elides its text on the left when the widget is too narrow.

    Unlike a plain QLabel, this one reacts to resize events and trims the
    display text with '…' so it always fits — the full text is never lost.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)

    def setFullText(self, text: str) -> None:
        self._full_text = text
        self._refresh()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        if not self._full_text:
            super().setText("")
            return
        fm = self.fontMetrics()
        elided = fm.elidedText(self._full_text, Qt.TextElideMode.ElideLeft, self.width())
        super().setText(elided)


class _VersionFetcher(QObject):
    """Fetches `node --version` and `npm --version` in a background thread."""

    versions_ready = pyqtSignal(str, str)   # (node_version, npm_version)

    def run(self) -> None:
        env = node_path_env()

        def _get(cmd: list[str]) -> str:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=6, env=env)
                return r.stdout.strip() if r.returncode == 0 else ""
            except Exception:
                return ""

        node_v = _get(["node", "--version"])
        npm_v  = _get(["npm",  "--version"])
        self.versions_ready.emit(node_v, npm_v)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._settings = AppSettings()
        self._settings.load()

        self._file_path: Optional[str] = None
        self._original_data: dict = {}
        self._deps: list[DependencyInfo] = []

        self._thread: Optional[QThread] = None
        self._worker: Optional[FetchWorker] = None
        self._fetch_completed = 0
        self._fetch_total = 0
        self._prev_page: int = 0
        self._min_age_at_settings_open: int = self._settings.min_age_days
        self._cache = NpmCache()
        self._pending_install_names: set[str] = set()
        self._node_version = ""          # filled in by _VersionFetcher
        self._ver_thread: Optional[QThread] = None

        self.setWindowTitle("Package.json Updater")
        self.setMinimumSize(1000, 600)
        self.resize(1280, 720)

        self._build_ui()
        self._set_chrome_visible(False)
        self._apply_palette()
        self._apply_stylesheet()
        self._table.set_dark(self._settings.dark_mode)
        self._table.set_merge_patch_minor(self._settings.merge_patch_minor)
        self._start_screen.set_recent(self._settings.recent_files)
        self._start_version_fetch()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._build_toolbar()

        central = QWidget()
        central.setObjectName("centralContent")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        self._filter_bar = self._build_filter_bar()
        layout.addWidget(self._filter_bar)
        _sp = self._filter_bar.sizePolicy()
        _sp.setRetainSizeWhenHidden(False)
        self._filter_bar.setSizePolicy(_sp)

        self._stack = QStackedWidget()

        # Page 0: start screen
        self._start_screen = StartScreen()
        self._start_screen.file_selected.connect(self._open_file)
        self._start_screen.recent_removed.connect(self._on_recent_removed)
        self._start_screen.recents_cleared.connect(self._on_recents_cleared)
        self._start_screen.open_folder_requested.connect(self._browse_folder)
        self._start_screen.open_file_requested.connect(self._browse_file)
        self._stack.addWidget(self._start_screen)

        # Page 1: dependency table (wrapped in a QFrame for rounded corners —
        # QAbstractScrollArea blocks parent painting at its corners on macOS,
        # so the frame carries the border/radius while the table has none).
        self._table = DependencyTable()
        self._table.update_requested.connect(self._on_update_requested)
        self._table.selection_changed.connect(self._on_selection_changed)
        _table_frame = QFrame()
        _table_frame.setObjectName("tableFrame")
        _table_frame_layout = QVBoxLayout(_table_frame)
        _table_frame_layout.setContentsMargins(0, 0, 0, 0)
        _table_frame_layout.setSpacing(0)
        _table_frame_layout.addWidget(self._table)
        self._stack.addWidget(_table_frame)

        # Page 2: settings
        self._settings_page = SettingsPage(self._settings)
        self._settings_page.settings_changed.connect(self._on_settings_changed)
        self._settings_page.back_requested.connect(self._on_settings_back)
        self._settings_page.cache_clear_requested.connect(self._cache.clear)
        self._stack.addWidget(self._settings_page)

        self._stack.setCurrentIndex(0)
        layout.addWidget(self._stack)

        self._action_bar = self._build_action_bar()
        layout.addWidget(self._action_bar)
        _sp = self._action_bar.sizePolicy()
        _sp.setRetainSizeWhenHidden(False)
        self._action_bar.setSizePolicy(_sp)

        self._build_status_bar_versions()

        self.statusBar().showMessage("No file loaded. Open a package.json to begin.")

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        act_open = QAction("📂  Open package.json", self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.triggered.connect(self._browse_file)
        tb.addAction(act_open)

        act_open_folder = QAction("📁  Open Folder", self)
        act_open_folder.triggered.connect(self._browse_folder)
        tb.addAction(act_open_folder)

        act_refresh = QAction("↺  Refresh", self)
        act_refresh.setShortcut(QKeySequence.StandardKey.Refresh)
        act_refresh.triggered.connect(lambda: self._start_fetch(bypass_cache=True))
        self._act_refresh = act_refresh
        tb.addAction(act_refresh)

        tb.addSeparator()

        act_settings = QAction("⚙  Settings", self)
        act_settings.triggered.connect(self._open_settings)
        tb.addAction(act_settings)

        # Spacer pushes the close button to the far right.
        # The file path lives in the status bar so it can never crowd the button.
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        self._act_close = QAction("✕  Close", self)
        self._act_close.triggered.connect(self._close_file)
        tb.addAction(self._act_close)

    def _build_filter_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("filterBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(12)

        show_label = QLabel("Show:")
        show_label.setObjectName("showLabel")
        layout.addWidget(show_label)

        self._group_combo = QComboBox()
        self._group_combo.addItem("All groups", None)
        self._group_combo.addItem("dependencies", "dependencies")
        self._group_combo.addItem("devDependencies", "devDependencies")
        self._group_combo.addItem("overrides", "overrides")
        self._group_combo.currentIndexChanged.connect(self._on_filter_changed)
        layout.addWidget(self._group_combo)

        self._hide_uptodate_cb = QCheckBox("Hide up-to-date")
        self._hide_uptodate_cb.setChecked(self._settings.hide_uptodate)
        self._hide_uptodate_cb.stateChanged.connect(self._on_filter_changed)
        layout.addWidget(self._hide_uptodate_cb)

        layout.addStretch()

        self._count_label = QLabel("")
        self._count_label.setObjectName("countLabel")
        layout.addWidget(self._count_label)

        return bar

    def _build_action_bar(self) -> QWidget:
        bar = QWidget()
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Thin horizontal separator at the top of the action bar
        sep = QFrame()
        sep.setObjectName("actionSep")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 0)
        row.setSpacing(8)

        self._btn_update_selected = QPushButton("Update Selected")
        self._btn_update_selected.setObjectName("btnBlue")
        self._btn_update_selected.setEnabled(False)
        self._btn_update_selected.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_update_selected.clicked.connect(self._update_selected)
        row.addWidget(self._btn_update_selected)

        self._update_mode = "patch_minor"

        # Split button: main action + dropdown arrow
        split = QWidget()
        split.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        split.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        split.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        split_lo = QHBoxLayout(split)
        split_lo.setContentsMargins(0, 0, 0, 0)
        split_lo.setSpacing(0)

        self._btn_update_all = QPushButton("Update All  ·  Patch / Minor")
        self._btn_update_all.setObjectName("btnUpdateAllMain")
        self._btn_update_all.setEnabled(False)
        self._btn_update_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_update_all.clicked.connect(self._update_all)
        split_lo.addWidget(self._btn_update_all)

        self._btn_update_all_arrow = QPushButton("▾")
        self._btn_update_all_arrow.setObjectName("btnUpdateAllArrow")
        self._btn_update_all_arrow.setEnabled(False)
        self._btn_update_all_arrow.setFixedWidth(26)
        self._btn_update_all_arrow.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._btn_update_all_arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_update_all_arrow.setToolTip("Choose update scope")
        self._btn_update_all_arrow.clicked.connect(self._show_update_mode_menu)
        split_lo.addWidget(self._btn_update_all_arrow)

        self._update_mode_menu = QMenu(self)
        self._act_patch_minor = self._update_mode_menu.addAction("Patch / Minor only")
        self._act_patch_minor.setCheckable(True)
        self._act_patch_minor.setChecked(True)
        self._act_all_major = self._update_mode_menu.addAction("All (including Major)")
        self._act_all_major.setCheckable(True)
        self._act_patch_minor.triggered.connect(lambda: self._set_update_mode("patch_minor"))
        self._act_all_major.triggered.connect(lambda: self._set_update_mode("all"))

        row.addWidget(split)

        self._btn_npm_install = QPushButton("📦  npm install")
        self._btn_npm_install.setObjectName("btnNpmInstall")
        self._btn_npm_install.setEnabled(False)
        self._btn_npm_install.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_npm_install.setToolTip("Run npm install in the project directory")
        self._btn_npm_install.clicked.connect(self._run_npm_install)
        row.addWidget(self._btn_npm_install)

        row.addStretch()

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setMaximumWidth(180)
        self._progress.setMaximumHeight(6)
        self._progress.setTextVisible(False)
        row.addWidget(self._progress)

        layout.addLayout(row)

        return bar

    def _build_status_bar_versions(self) -> None:
        """Pin node/npm/nvmrc labels and the file path to the status bar.

        addPermanentWidget appends left-to-right, so the file path label is
        added first (leftmost permanent widget) and the version labels are
        added second (rightmost), giving: message | path | node · npm.
        """
        sb = self.statusBar()

        # ── version labels (right side) ───────────────────────────────────────
        versions = QWidget()
        lo = QHBoxLayout(versions)
        lo.setContentsMargins(0, 0, 8, 0)
        lo.setSpacing(0)

        self._footer_nvmrc = QLabel()
        self._footer_nvmrc.setObjectName("footerNvmrc")
        self._footer_nvmrc.setVisible(False)
        lo.addWidget(self._footer_nvmrc)

        self._footer_sep_nvmrc = QLabel("  ·  ")
        self._footer_sep_nvmrc.setObjectName("footerSep")
        self._footer_sep_nvmrc.setVisible(False)
        lo.addWidget(self._footer_sep_nvmrc)

        self._footer_node = QLabel("node …")
        self._footer_node.setObjectName("footerVersion")
        lo.addWidget(self._footer_node)

        sep = QLabel("  ·  ")
        sep.setObjectName("footerSep")
        lo.addWidget(sep)

        self._footer_npm = QLabel("npm …")
        self._footer_npm.setObjectName("footerVersion")
        lo.addWidget(self._footer_npm)

        # ── file path label (added first → leftmost permanent widget) ───────────
        self._file_label = _ElidingLabel()
        self._file_label.setObjectName("fileLabel")
        self._file_label.setVisible(False)
        self._file_label.setMaximumWidth(360)
        sb.addPermanentWidget(self._file_label)

        # ── version labels (added second → to the right of path label) ──────────
        sb.addPermanentWidget(versions)

    def _start_version_fetch(self) -> None:
        """Spawn a background thread to retrieve node/npm version strings."""
        fetcher = _VersionFetcher()
        thread = QThread(self)
        fetcher.moveToThread(thread)
        thread.started.connect(fetcher.run)
        fetcher.versions_ready.connect(thread.quit)
        fetcher.versions_ready.connect(fetcher.deleteLater)
        fetcher.versions_ready.connect(self._on_versions_fetched)
        thread.finished.connect(thread.deleteLater)
        self._ver_thread = thread
        self._ver_fetcher = fetcher   # keep a ref so Python doesn't GC it
        thread.start()

    def _on_versions_fetched(self, node_v: str, npm_v: str) -> None:
        self._ver_thread = None
        self._ver_fetcher = None
        self._node_version = node_v
        self._footer_node.setText(f"node {node_v}" if node_v else "node —")
        self._footer_npm.setText(f"npm {npm_v}" if npm_v else "npm —")
        # Re-colour .nvmrc now that we know the installed node version
        if self._file_path:
            self._update_nvmrc(os.path.dirname(self._file_path))

    def _update_nvmrc(self, project_dir: Optional[str]) -> None:
        """Show/hide the .nvmrc label; warn when major version mismatches node."""
        if not project_dir:
            self._footer_nvmrc.setVisible(False)
            self._footer_sep_nvmrc.setVisible(False)
            return

        nvmrc_path = os.path.join(project_dir, ".nvmrc")
        if not os.path.isfile(nvmrc_path):
            self._footer_nvmrc.setVisible(False)
            self._footer_sep_nvmrc.setVisible(False)
            return

        try:
            with open(nvmrc_path) as fh:
                nvmrc_ver = fh.read().strip()
        except Exception:
            self._footer_nvmrc.setVisible(False)
            self._footer_sep_nvmrc.setVisible(False)
            return

        self._footer_nvmrc.setText(f".nvmrc: {nvmrc_ver}")

        # Warn when installed node major ≠ .nvmrc major (if we can parse both)
        warn = False
        if self._node_version and nvmrc_ver:
            try:
                node_maj  = int(self._node_version.lstrip("v").split(".")[0])
                nvmrc_maj = int(nvmrc_ver.lstrip("v").split(".")[0])
                warn = node_maj != nvmrc_maj
            except (ValueError, IndexError):
                pass

        new_name = "footerNvmrcWarn" if warn else "footerNvmrc"
        if self._footer_nvmrc.objectName() != new_name:
            self._footer_nvmrc.setObjectName(new_name)
            self._footer_nvmrc.style().unpolish(self._footer_nvmrc)
            self._footer_nvmrc.style().polish(self._footer_nvmrc)

        self._footer_nvmrc.setVisible(True)
        self._footer_sep_nvmrc.setVisible(True)

    def _set_chrome_visible(self, visible: bool) -> None:
        """Show or hide the table-specific UI (filter bar, action bar, toolbar items)."""
        self._filter_bar.setVisible(visible)
        self._action_bar.setVisible(visible)
        self._act_refresh.setVisible(visible)
        self._act_close.setVisible(visible)
        self._file_label.setVisible(visible)

    # ── pending-install persistence ───────────────────────────────────────────

    def _save_pending(self) -> None:
        if not self._file_path:
            return
        if self._pending_install_names:
            self._settings.pending_installs[self._file_path] = list(self._pending_install_names)
        else:
            self._settings.pending_installs.pop(self._file_path, None)
        self._settings.save()

    # ── recents management ────────────────────────────────────────────────────

    def _on_recent_removed(self, path: str) -> None:
        self._settings.recent_files = [
            r for r in self._settings.recent_files if r.get("path") != path
        ]
        self._settings.save()
        self._start_screen.set_recent(self._settings.recent_files)

    def _on_recents_cleared(self) -> None:
        self._settings.recent_files = []
        self._settings.save()
        self._start_screen.set_recent(self._settings.recent_files)

    # ── file open ─────────────────────────────────────────────────────────────

    def _browse_file(self) -> None:
        start_dir = (
            os.path.dirname(self._settings.last_opened_path)
            if self._settings.last_opened_path
            else os.path.expanduser("~")
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open package.json",
            start_dir,
            "JSON Files (package.json);;All Files (*)",
        )
        self.activateWindow()   # re-activate after native macOS dialog steals focus
        if path:
            self._open_file(path)

    def _browse_folder(self) -> None:
        start_dir = (
            os.path.dirname(os.path.dirname(self._settings.last_opened_path))
            if self._settings.last_opened_path
            else os.path.expanduser("~")
        )
        folder = QFileDialog.getExistingDirectory(
            self, "Open Folder containing package.json", start_dir
        )
        self.activateWindow()   # re-activate after native macOS dialog steals focus
        if not folder:
            return
        candidate = os.path.join(folder, "package.json")
        if os.path.isfile(candidate):
            self._open_file(candidate)
        else:
            QMessageBox.warning(
                self,
                "No package.json found",
                f"No package.json was found in:\n{folder}",
            )

    def _open_file(self, path: str) -> None:
        try:
            original_data, deps = load_package(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Could not read package.json:\n{exc}")
            return

        self._file_path = path
        self._original_data = original_data
        self._deps = deps
        self._settings.last_opened_path = path
        self._settings.add_recent(path)
        self._settings.save()
        self._start_screen.set_recent(self._settings.recent_files)

        self._file_label.setFullText(path)
        self.setWindowTitle(f"Package.json Updater — {os.path.basename(os.path.dirname(path))}")

        self._table.populate(deps)
        self._pending_install_names |= set(self._settings.pending_installs.get(path, []))
        for dep in self._deps:
            if dep.name in self._pending_install_names:
                dep.needs_install = True
        self._table.set_hide_uptodate(self._hide_uptodate_cb.isChecked())
        self._btn_update_selected.setEnabled(False)   # all checkboxes reset by populate
        self._btn_npm_install.setEnabled(True)
        self._set_chrome_visible(True)
        self._stack.setCurrentIndex(1)
        self._update_count_label()
        self._update_nvmrc(os.path.dirname(path))
        self._start_fetch()

    def _close_file(self) -> None:
        """Cancel any running fetch, clear state, and return to the start screen."""
        self._cancel_fetch()
        self._file_path = None
        self._original_data = {}
        self._deps = []
        self._table.populate([])
        self._btn_update_selected.setEnabled(False)
        self._btn_update_all.setEnabled(False)
        self._btn_update_all_arrow.setEnabled(False)
        self._btn_npm_install.setEnabled(False)
        self._count_label.setText("")
        self._set_chrome_visible(False)
        self._stack.setCurrentIndex(0)
        self.setWindowTitle("Package.json Updater")
        self.statusBar().showMessage("No file loaded. Open a package.json to begin.")
        self._update_nvmrc(None)

    # ── fetch ──────────────────────────────────────────────────────────────────

    def _start_fetch(self, bypass_cache: bool = False) -> None:
        if not self._deps:
            return
        self._cancel_fetch()

        # Mark all deps as loading
        for dep in self._deps:
            dep.fetch_status = "loading"
            dep.latest_patch = dep.latest_minor = dep.latest_major = None
            dep.patch_age = dep.minor_age = dep.major_age = None
            self._table.update_row(dep)

        self._fetch_completed = 0
        self._fetch_total = len(self._deps)
        self._progress.setMaximum(self._fetch_total)
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._btn_update_all.setEnabled(False)
        self._btn_update_all_arrow.setEnabled(False)
        self._table.set_checkboxes_enabled(False)

        self._worker = FetchWorker(
            self._deps,
            self._settings.min_age_days,
            cache=self._cache,
            cache_ttl_hours=self._settings.cache_ttl_hours,
            bypass_cache=bypass_cache,
        )
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_fetch_finished)
        # Clear Python refs AFTER _on_fetch_finished so that closeEvent never
        # calls isRunning() on an already-deleted C++ QThread object.
        self._thread.finished.connect(self._on_thread_cleanup)

        self._worker.package_ready.connect(self._on_package_ready)
        self._worker.progress.connect(self._on_progress)
        self._worker.error.connect(self._on_fetch_error)

        self._thread.start()
        self.statusBar().showMessage(f"Fetching updates for {self._fetch_total} packages…")

    def _cancel_fetch(self) -> None:
        if self._worker:
            self._worker.cancel()
        if self._thread:
            try:
                if self._thread.isRunning():
                    self._thread.quit()
                    self._thread.wait(2000)
            except RuntimeError:
                pass  # C++ object already deleted; nothing to wait for
        self._worker = None
        self._thread = None

    def _on_thread_cleanup(self) -> None:
        """Null out Python references once the thread has finished naturally.

        Called last on thread.finished (after _on_fetch_finished), so by the
        time closeEvent runs there is no stale C++ pointer to stumble on.
        """
        self._thread = None
        self._worker = None

    def _on_package_ready(self, name: str, updates: dict) -> None:
        for dep in self._deps_by_name(name):
            dep.fetch_status = "done"
            dep.latest_patch = updates.get("latest_patch")
            dep.latest_minor = updates.get("latest_minor")
            dep.latest_major = updates.get("latest_major")
            dep.patch_age = updates.get("patch_age")
            dep.minor_age = updates.get("minor_age")
            dep.major_age = updates.get("major_age")
            dep.repo_url = updates.get("repo_url")
            self._table.update_row(dep)

    def _on_progress(self, completed: int, total: int) -> None:
        self._fetch_completed = completed
        self._progress.setValue(completed)
        self.statusBar().showMessage(
            f"Fetching updates… {completed}/{total} packages checked"
        )

    def _on_fetch_error(self, name: str, message: str) -> None:
        for dep in self._deps_by_name(name):
            dep.fetch_status = "error"
            dep.error_message = message
            self._table.update_row(dep)

    def _on_fetch_finished(self) -> None:
        self._progress.setVisible(False)
        self._btn_update_all.setEnabled(True)
        self._btn_update_all_arrow.setEnabled(True)
        self._table.set_checkboxes_enabled(True)
        # Update Selected is enabled by checkbox selection, not fetch completion.
        self._update_count_label()

        if self._file_path:
            self._settings.update_last_checked(self._file_path)
            self._start_screen.set_recent(self._settings.recent_files)

        has_updates = any(d.has_any_update for d in self._deps)
        errors = sum(1 for d in self._deps if d.fetch_status == "error")

        msg_parts = [f"Done — {len(self._deps)} packages checked."]
        if has_updates:
            n = sum(1 for d in self._deps if d.has_any_update)
            msg_parts.append(f"{n} have available updates.")
        else:
            msg_parts.append("All packages are up-to-date.")
        if errors:
            msg_parts.append(f"{errors} fetch error(s).")
        self.statusBar().showMessage("  ".join(msg_parts))

    # ── update ────────────────────────────────────────────────────────────────

    def _on_update_requested(self, dep: DependencyInfo, version: str) -> None:
        """Single-dependency ↑ button: write, patch state in place, no re-fetch."""
        if not self._file_path:
            return

        try:
            save_package(self._file_path, self._original_data, [(dep, version)])
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Failed to write package.json:\n{exc}")
            return

        # Keep _original_data in sync so subsequent saves don't clobber this write.
        try:
            new_data, _ = load_package(self._file_path)
            self._original_data = new_data
        except Exception:
            pass

        # Drop this dep from cache — invalidate BEFORE overwriting current_version
        # so the key (name@old_version) still matches what was stored.
        self._cache.invalidate(dep.name, dep.current_version)

        # Update the dep in memory.
        from core.semver_utils import apply_prefix
        dep.raw_constraint = apply_prefix(dep.raw_constraint, version)
        dep.current_version = version
        dep.needs_install = True
        self._pending_install_names.add(dep.name)
        self._save_pending()

        # Clear whichever bump columns are no longer upgrades from the new baseline.
        if dep.latest_major == version:
            dep.latest_patch = dep.latest_minor = dep.latest_major = None
            dep.patch_age   = dep.minor_age   = dep.major_age   = None
        elif dep.latest_minor == version:
            dep.latest_patch = dep.latest_minor = None
            dep.patch_age   = dep.minor_age   = None
        elif dep.latest_patch == version:
            dep.latest_patch = None
            dep.patch_age   = None

        self._table.update_row(dep)
        self._update_count_label()
        self._settings.update_last_checked(self._file_path)
        self._start_screen.set_recent(self._settings.recent_files)
        self.statusBar().showMessage(
            f"✓  {dep.name} updated to {version} — run npm install to apply."
        )

    def _on_selection_changed(self) -> None:
        """Enable / disable Update Selected based on checkbox state."""
        self._btn_update_selected.setEnabled(
            bool(self._table.get_selected_deps())
        )

    def _set_update_mode(self, mode: str) -> None:
        self._update_mode = mode
        self._act_patch_minor.setChecked(mode == "patch_minor")
        self._act_all_major.setChecked(mode == "all")
        label = "Patch / Minor" if mode == "patch_minor" else "All incl. Major"
        self._btn_update_all.setText(f"Update All  ·  {label}")

    def _show_update_mode_menu(self) -> None:
        btn = self._btn_update_all_arrow
        self._update_mode_menu.exec(
            btn.mapToGlobal(btn.rect().bottomLeft())
        )

    def _update_selected(self) -> None:
        checked = self._table.get_selected_deps()
        if not checked:
            QMessageBox.information(
                self,
                "Nothing selected",
                "Check at least one package checkbox to use Update Selected.",
            )
            return
        mode = self._update_mode
        updates = [
            (dep, target)
            for dep in checked
            if (target := self._best_version_for_mode(dep, mode))
        ]
        if not updates:
            QMessageBox.information(
                self,
                "Nothing to update",
                "The selected packages have no available updates for the chosen mode.",
            )
            return
        self._write_updates(updates)

    def _update_all(self) -> None:
        mode = self._update_mode
        updates: list[tuple[DependencyInfo, str]] = []

        for dep in self._deps:
            target = self._best_version_for_mode(dep, mode)
            if target:
                updates.append((dep, target))

        if not updates:
            QMessageBox.information(
                self,
                "Nothing to update",
                "No packages have available updates matching the selected mode.",
            )
            return

        mode_label = "Patch & Minor only" if mode == "patch_minor" else "All (including Major)"
        answer = QMessageBox.question(
            self,
            "Confirm Update All",
            f"Update {len(updates)} package(s) using mode: <b>{mode_label}</b>?\n\n"
            "This will overwrite your package.json.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._write_updates(updates)

    def _best_version_for_mode(
        self, dep: DependencyInfo, mode: str
    ) -> Optional[str]:
        """Return the best target version for a dep given the update mode."""
        if mode == "patch_minor":
            return dep.latest_minor or dep.latest_patch
        else:  # 'all'
            return dep.latest_major or dep.latest_minor or dep.latest_patch

    def _write_updates(self, updates: list[tuple[DependencyInfo, str]]) -> None:
        if not self._file_path:
            return
        try:
            save_package(self._file_path, self._original_data, updates)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Failed to write package.json:\n{exc}")
            return

        # Update in-memory state and drop outdated cache entries.
        # Invalidate BEFORE overwriting current_version so the key matches.
        for dep, new_version in updates:
            self._cache.invalidate(dep.name, dep.current_version)
            from core.semver_utils import apply_prefix
            dep.raw_constraint = apply_prefix(dep.raw_constraint, new_version)
            dep.current_version = new_version
            self._pending_install_names.add(dep.name)

        self._save_pending()
        QMessageBox.information(
            self,
            "Updated",
            f"{len(updates)} package(s) updated in package.json.\n\n"
            "Run 'npm install' to apply the changes.",
        )
        # Reload and refresh
        self._open_file(self._file_path)

    # ── npm install ───────────────────────────────────────────────────────────

    def _run_npm_install(self) -> None:
        if not self._file_path:
            return
        project_dir = os.path.dirname(self._file_path)
        dialog = NpmInstallDialog(project_dir, parent=self)
        dialog.succeeded.connect(self._on_npm_install_succeeded)

    def _on_npm_install_succeeded(self) -> None:
        self._pending_install_names.clear()
        self._save_pending()
        for dep in self._deps:
            if dep.needs_install:
                dep.needs_install = False
                self._table.update_row(dep)

    # ── filters ───────────────────────────────────────────────────────────────

    def _on_filter_changed(self) -> None:
        group = self._group_combo.currentData()
        hide = self._hide_uptodate_cb.isChecked()
        self._table.set_filter_group(group)
        self._table.set_hide_uptodate(hide)
        self._settings.hide_uptodate = hide
        self._settings.save()
        self._update_count_label()

    def _update_count_label(self) -> None:
        total = len(self._deps)
        done = sum(1 for d in self._deps if d.fetch_status == "done")
        have_updates = sum(1 for d in self._deps if d.has_any_update)
        self._count_label.setText(
            f"{total} packages  ·  {done} checked  ·  {have_updates} with updates"
        )

    # ── settings ──────────────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        if self._stack.currentIndex() != 2:
            self._prev_page = self._stack.currentIndex()
            self._min_age_at_settings_open = self._settings.min_age_days
        self._settings_page.refresh(self._settings)
        self._filter_bar.setVisible(False)
        self._action_bar.setVisible(False)
        self._stack.setCurrentIndex(2)

    def _on_settings_back(self) -> None:
        self._stack.setCurrentIndex(self._prev_page)
        # Re-show chrome only when returning to the table page
        if self._prev_page == 1:
            self._filter_bar.setVisible(True)
            self._action_bar.setVisible(True)

    def _on_settings_changed(self, settings: AppSettings) -> None:
        self._settings = settings
        self._apply_palette()
        self._apply_stylesheet()
        self._table.set_dark(settings.dark_mode)
        self._table.set_merge_patch_minor(settings.merge_patch_minor)
        if self._file_path and settings.min_age_days != self._min_age_at_settings_open:
            self._min_age_at_settings_open = settings.min_age_days
            self._start_fetch(bypass_cache=True)

    def _apply_palette(self) -> None:
        """
        Set the application QPalette to match the current theme.

        Fusion style paints some widgets (ComboBox popups, spinboxes, tooltips)
        directly from the palette rather than the stylesheet.  On macOS, Qt6
        automatically inherits the system dark palette, which overrides our
        stylesheet colours for those floating widgets.  Explicitly setting the
        palette here keeps every widget in sync with our own light/dark toggle.
        """
        p = QPalette()
        if self._settings.dark_mode:
            p.setColor(QPalette.ColorRole.Window,          QColor("#0f172a"))
            p.setColor(QPalette.ColorRole.WindowText,      QColor("#e2e8f0"))
            p.setColor(QPalette.ColorRole.Base,            QColor("#1e293b"))
            p.setColor(QPalette.ColorRole.AlternateBase,   QColor("#172032"))
            p.setColor(QPalette.ColorRole.Text,            QColor("#e2e8f0"))
            p.setColor(QPalette.ColorRole.BrightText,      QColor("#f1f5f9"))
            p.setColor(QPalette.ColorRole.Button,          QColor("#1e293b"))
            p.setColor(QPalette.ColorRole.ButtonText,      QColor("#e2e8f0"))
            p.setColor(QPalette.ColorRole.Highlight,       QColor("#3b82f6"))
            p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
            p.setColor(QPalette.ColorRole.ToolTipBase,     QColor("#1e293b"))
            p.setColor(QPalette.ColorRole.ToolTipText,     QColor("#e2e8f0"))
            p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#475569"))
            # Border tones used by Fusion for popup/frame outlines
            p.setColor(QPalette.ColorRole.Light,           QColor("#475569"))
            p.setColor(QPalette.ColorRole.Mid,             QColor("#334155"))
            p.setColor(QPalette.ColorRole.Dark,            QColor("#334155"))
            p.setColor(QPalette.ColorRole.Shadow,          QColor("#0f172a"))
        else:
            p.setColor(QPalette.ColorRole.Window,          QColor("#f8fafc"))
            p.setColor(QPalette.ColorRole.WindowText,      QColor("#0f172a"))
            p.setColor(QPalette.ColorRole.Base,            QColor("#ffffff"))
            p.setColor(QPalette.ColorRole.AlternateBase,   QColor("#f8fafc"))
            p.setColor(QPalette.ColorRole.Text,            QColor("#0f172a"))
            p.setColor(QPalette.ColorRole.BrightText,      QColor("#ffffff"))
            p.setColor(QPalette.ColorRole.Button,          QColor("#f1f5f9"))
            p.setColor(QPalette.ColorRole.ButtonText,      QColor("#0f172a"))
            p.setColor(QPalette.ColorRole.Highlight,       QColor("#3b82f6"))
            p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
            p.setColor(QPalette.ColorRole.ToolTipBase,     QColor("#ffffff"))
            p.setColor(QPalette.ColorRole.ToolTipText,     QColor("#0f172a"))
            p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#94a3b8"))
            # Border tones used by Fusion for popup/frame outlines
            p.setColor(QPalette.ColorRole.Light,           QColor("#ffffff"))
            p.setColor(QPalette.ColorRole.Mid,             QColor("#e2e8f0"))
            p.setColor(QPalette.ColorRole.Dark,            QColor("#cbd5e1"))
            p.setColor(QPalette.ColorRole.Shadow,          QColor("#cbd5e1"))
        QApplication.instance().setPalette(p)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _dep_by_name(self, name: str) -> Optional[DependencyInfo]:
        for dep in self._deps:
            if dep.name == name:
                return dep
        return None

    def _deps_by_name(self, name: str) -> list[DependencyInfo]:
        return [dep for dep in self._deps if dep.name == name]

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._cancel_fetch()
        if self._ver_thread:
            try:
                self._ver_thread.quit()
                self._ver_thread.wait(2000)
            except RuntimeError:
                pass
        super().closeEvent(event)

    # ── stylesheet ────────────────────────────────────────────────────────────

    def _apply_stylesheet(self) -> None:
        if self._settings.dark_mode:
            self.setStyleSheet(self._dark_stylesheet())
        else:
            self.setStyleSheet(self._light_stylesheet())

    @staticmethod
    def _light_stylesheet() -> str:
        return ("""
            * { font-size: 15px; }
            QLabel { color: #334155; }
            QMainWindow, QStackedWidget { background: #f8fafc; }
            QWidget#centralContent { background: #f8fafc; }
            QToolTip {
                background: #ffffff; color: #0f172a;
                border: 1px solid #e2e8f0; border-radius: 6px;
                padding: 4px 8px; font-size: 13px;
            }
            /* Toolbar */
            QToolBar {
                background: #ffffff;
                border: none;
                border-bottom: 1px solid #e2e8f0;
                padding: 4px 10px;
                spacing: 2px;
            }
            QToolBar::separator { background: #e2e8f0; width: 1px; margin: 5px 6px; }
            QToolBar QToolButton {
                color: #334155; border: none; border-radius: 6px; padding: 6px 12px;
            }
            QToolBar QToolButton:hover  { background: #f1f5f9; }
            QToolBar QToolButton:pressed { background: #e2e8f0; }
            QToolBar QToolButton[text="✕  Close"]         { color: #ef4444; }
            QToolBar QToolButton[text="✕  Close"]:hover   { background: #fee2e2; color: #dc2626; }
            QToolBar QToolButton[text="✕  Close"]:pressed { background: #fecaca; color: #b91c1c; }
            QLabel#fileLabel { color: #94a3b8; font-size: 13px; padding: 0 8px; }
            /* Filter bar */
            QFrame#filterBar {
                background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px;
            }
            QLabel#showLabel { color: #64748b; font-weight: 600; font-size: 14px; }
            /* Start screen */
            QWidget#startScreen  { background: transparent; }
            QLabel#startIcon     { font-size: 48px; }
            QLabel#startTitle    { font-size: 24px; font-weight: 700; color: #0f172a; }
            QLabel#startSubtitle { font-size: 15px; color: #64748b; }
            QPushButton#startBtnPrimary {
                background: #3b82f6; color: #ffffff; border: none;
                border-radius: 8px; padding: 10px 22px; font-weight: 600; min-width: 170px;
            }
            QPushButton#startBtnPrimary:hover   { background: #2563eb; }
            QPushButton#startBtnPrimary:pressed { background: #1d4ed8; }
            QPushButton#startBtnSecondary {
                background: #ffffff; color: #334155;
                border: 1.5px solid #e2e8f0; border-radius: 8px;
                padding: 10px 22px; font-weight: 600; min-width: 140px;
            }
            QPushButton#startBtnSecondary:hover   { background: #f1f5f9; border-color: #94a3b8; }
            QPushButton#startBtnSecondary:pressed { background: #e2e8f0; }
            QLabel#recentHeader { font-size: 13px; font-weight: 700; color: #94a3b8; letter-spacing: 1px; }
            QPushButton#recentClearBtn {
                background: transparent; color: #94a3b8; border: none;
                font-size: 13px; font-weight: 600; padding: 0 2px;
            }
            QPushButton#recentClearBtn:hover   { color: #ef4444; }
            QPushButton#recentClearBtn:pressed { color: #dc2626; }
            QFrame#recentRow { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; }
            QFrame#recentRow:hover { background: #eff6ff; border-color: #bfdbfe; }
            QLabel#recentName { font-size: 15px; font-weight: 600; color: #1e293b; }
            QLabel#recentPath { font-size: 13px; color: #94a3b8; }
            QLabel#recentAge  { font-size: 13px; color: #64748b; }
            QPushButton#recentRemoveBtn {
                background: transparent; color: #cbd5e1; border: none;
                font-size: 16px; border-radius: 4px; padding: 0;
            }
            QPushButton#recentRemoveBtn:hover   { background: #fee2e2; color: #ef4444; }
            QPushButton#recentRemoveBtn:pressed { background: #fecaca; color: #dc2626; }
            QLabel#noRecent   { font-size: 15px; color: #94a3b8; padding: 20px; }
            /* Table */
            QFrame#tableFrame {
                border: 1px solid #e2e8f0;
                border-radius: 10px;
            }
            QTableWidget {
                border: none; border-radius: 0; background: #ffffff;
                gridline-color: transparent; outline: none;
                selection-background-color: transparent; alternate-background-color: #f8fafc;
            }
            QTableWidget::item { padding: 0 10px; border-bottom: 1px solid #f1f5f9; color: #1e293b; }
            QTableWidget::item:selected           { background: #eff6ff; color: #1e293b; }
            QTableWidget::item:alternate          { background: #f8fafc; }
            QTableWidget::item:alternate:selected { background: #eff6ff; }
            QHeaderView { border: none; }
            QHeaderView::section {
                background: #f8fafc; color: #64748b; font-size: 13px; font-weight: 700;
                border: none; border-bottom: 1px solid #e2e8f0; padding: 8px 10px;
            }
            QHeaderView::section:first { border-top-left-radius: 9px; }
            QHeaderView::section:last  { border-top-right-radius: 9px; }
            QLabel#pkgName { color: #1e293b; background: transparent; }
            QPushButton#pkgLinkBtn {
                background: #eff6ff; border: 1px solid #bfdbfe;
                color: #3b82f6; font-size: 12px; font-weight: 600;
                border-radius: 4px; padding: 0 7px;
            }
            QPushButton#pkgLinkBtn:hover   { background: #dbeafe; border-color: #93c5fd; color: #1d4ed8; }
            QPushButton#pkgLinkBtn:pressed { background: #bfdbfe; border-color: #60a5fa; color: #1e40af; }
            QLabel#pkgPendingChip {
                background: #fef3c7; color: #92400e;
                border: 1px solid #fcd34d; border-radius: 4px;
                font-size: 12px; font-weight: 600; padding: 0 7px;
            }
            /* Scrollbars */
            QScrollBar:vertical   { background: transparent; width: 8px;  margin: 4px 2px; }
            QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px 4px; }
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
                background: #cbd5e1; border-radius: 4px; min-height: 28px; min-width: 28px;
            }
            QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: #94a3b8; }
            QScrollBar::add-line:vertical,  QScrollBar::sub-line:vertical  { height: 0; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
            QTableCornerButton::section {
                background: #f8fafc; border: none;
                border-bottom: 1px solid #e2e8f0; border-right: 1px solid #e2e8f0;
            }
            /* ComboBox */
            QComboBox {
                border: 1px solid #e2e8f0; border-radius: 6px; padding: 5px 10px;
                background: #ffffff; color: #334155; min-height: 30px;
                selection-background-color: #eff6ff;
            }
            QComboBox:hover { border-color: #94a3b8; }
            QComboBox:focus { border-color: #3b82f6; }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView {
                border: 1px solid #e2e8f0; background: #ffffff; outline: none;
                selection-background-color: #eff6ff; selection-color: #1e293b;
            }
            /* CheckBox */
            QCheckBox { color: #334155; spacing: 7px; }
            QCheckBox::indicator {
                width: 16px; height: 16px; border: 2px solid #9ca3af;
                border-radius: 4px; background: #ffffff;
            }
            QCheckBox::indicator:hover   { border-color: #6b7280; }
            QCheckBox::indicator:checked { background: #3b82f6; border-color: #3b82f6; image: url(§CHECK§); }
            /* Table row checkbox — 20×20 QPushButton centred in a transparent container */
            QPushButton#tableCheckbox {
                background: #ffffff; border: 2px solid #9ca3af;
                border-radius: 4px; padding: 0;
            }
            QPushButton#tableCheckbox:hover    { border-color: #6b7280; }
            QPushButton#tableCheckbox:checked  { background: #3b82f6; border-color: #3b82f6; image: url(§CB_C§); }
            QPushButton#tableCheckbox:disabled { border-color: #e2e8f0; background: #f1f5f9; }
            /* Action bar */
            QFrame#actionSep { color: #e2e8f0; background: #e2e8f0; max-height: 1px; border: none; }
            QPushButton#btnBlue {
                background: #3b82f6; color: #ffffff; border: none;
                border-radius: 7px; padding: 7px 18px; font-weight: 600; min-height: 32px;
            }
            QPushButton#btnBlue:hover     { background: #2563eb; }
            QPushButton#btnBlue:pressed   { background: #1d4ed8; }
            QPushButton#btnBlue:disabled  { background: #bfdbfe; }
            QPushButton#btnPurple {
                background: #8b5cf6; color: #ffffff; border: none;
                border-radius: 7px; padding: 7px 18px; font-weight: 600; min-height: 32px;
            }
            QPushButton#btnPurple:hover    { background: #7c3aed; }
            QPushButton#btnPurple:pressed  { background: #6d28d9; }
            QPushButton#btnPurple:disabled { background: #ddd6fe; }
            QPushButton#btnUpdateAllMain {
                background: #8b5cf6; color: #ffffff; border: none;
                border-top-left-radius: 7px; border-bottom-left-radius: 7px;
                border-top-right-radius: 0; border-bottom-right-radius: 0;
                padding: 7px 14px; font-weight: 600; min-height: 32px;
            }
            QPushButton#btnUpdateAllMain:hover   { background: #7c3aed; }
            QPushButton#btnUpdateAllMain:pressed { background: #6d28d9; }
            QPushButton#btnUpdateAllMain:disabled { background: #ddd6fe; color: #a78bfa; }
            QPushButton#btnUpdateAllArrow {
                background: #8b5cf6; color: #ffffff; border: none;
                border-top-right-radius: 7px; border-bottom-right-radius: 7px;
                border-top-left-radius: 0; border-bottom-left-radius: 0;
                border-left: 1px solid #a78bfa;
                padding: 0; font-size: 14px; min-height: 32px;
            }
            QPushButton#btnUpdateAllArrow:hover   { background: #7c3aed; }
            QPushButton#btnUpdateAllArrow:pressed { background: #6d28d9; }
            QPushButton#btnUpdateAllArrow:disabled { background: #ddd6fe; color: #c4b5fd; border-left-color: #c4b5fd; }
            QPushButton#btnDanger {
                background: #ef4444; color: #ffffff; border: none;
                border-radius: 7px; padding: 7px 18px; font-weight: 600; min-height: 32px;
            }
            QPushButton#btnDanger:hover   { background: #dc2626; }
            QPushButton#btnDanger:pressed { background: #b91c1c; }
            QPushButton#btnGhost {
                background: transparent; color: #64748b;
                border: 1.5px solid #e2e8f0; border-radius: 7px;
                padding: 7px 18px; font-weight: 500; min-height: 32px;
            }
            QPushButton#btnGhost:hover   { background: #f1f5f9; border-color: #94a3b8; }
            QPushButton#btnGhost:pressed { background: #e2e8f0; }
            /* Progress */
            QProgressBar { border: none; border-radius: 3px; background: #e2e8f0; max-height: 6px; }
            QProgressBar::chunk {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #3b82f6, stop:1 #60a5fa);
                border-radius: 3px;
            }
            /* npm install button */
            QPushButton#btnNpmInstall {
                background: #f1f5f9; color: #334155;
                border: 1.5px solid #e2e8f0; border-radius: 7px;
                padding: 7px 18px; font-weight: 600; min-height: 32px;
            }
            QPushButton#btnNpmInstall:hover    { background: #e2e8f0; border-color: #94a3b8; }
            QPushButton#btnNpmInstall:pressed  { background: #cbd5e1; }
            QPushButton#btnNpmInstall:disabled { background: #f8fafc; color: #94a3b8; border-color: #e2e8f0; }
            /* npm install modal */
            QFrame#npmCard {
                background: #ffffff; border-radius: 12px;
                border: 1px solid #e2e8f0;
            }
            QLabel#npmCardTitle { font-size: 18px; font-weight: 600; color: #0f172a; }
            QLabel#npmStatusRunning { color: #64748b; font-size: 15px; }
            QLabel#npmStatusOk      { color: #15803d; font-size: 15px; font-weight: 600; }
            QLabel#npmStatusError   { color: #dc2626; font-size: 15px; font-weight: 600; }
            QPushButton#npmToggle {
                background: #f8fafc; color: #64748b;
                border: 1px solid #e2e8f0; border-radius: 6px;
                padding: 6px 12px; font-size: 14px; font-weight: 600;
                text-align: left;
            }
            QPushButton#npmToggle:hover   { background: #f1f5f9; color: #334155; }
            QPushButton#npmToggle:checked { background: #f1f5f9; color: #334155; }
            QTextEdit#npmOutput {
                background: #0f172a; color: #e2e8f0;
                border: 1px solid #334155; border-radius: 6px;
                selection-background-color: #334155;
            }
            /* Version cell widgets */
            QLabel#tableEmptyMsg { color: #94a3b8; font-size: 15px; background: transparent; }
            QLabel#vcwLoading { color: #94a3b8; font-style: italic; font-size: 14px; }
            QLabel#vcwError   { color: #ef4444; font-size: 14px; }
            QLabel#vcwNone    { color: #cbd5e1; font-size: 16px; }
            QLabel#vcwVersion { color: #1e293b; font-size: 14px; font-weight: 600; }
            QLabel#vcwAge     { color: #64748b; font-size: 13px; }
            QPushButton#vcwBtnPatch {
                background: #dbeafe; color: #1d4ed8;
                border: 1.5px solid #93c5fd; border-radius: 6px;
                font-size: 16px; font-weight: 700;
            }
            QPushButton#vcwBtnPatch:hover   { background: #bfdbfe; border-color: #60a5fa; }
            QPushButton#vcwBtnPatch:pressed { background: #93c5fd; border-color: #3b82f6; }
            QPushButton#vcwBtnMinor {
                background: #dcfce7; color: #15803d;
                border: 1.5px solid #86efac; border-radius: 6px;
                font-size: 16px; font-weight: 700;
            }
            QPushButton#vcwBtnMinor:hover   { background: #bbf7d0; border-color: #4ade80; }
            QPushButton#vcwBtnMinor:pressed { background: #86efac; border-color: #22c55e; }
            QPushButton#vcwBtnMajor {
                background: #fef9c3; color: #92400e;
                border: 1.5px solid #fcd34d; border-radius: 6px;
                font-size: 16px; font-weight: 700;
            }
            QPushButton#vcwBtnMajor:hover   { background: #fde68a; border-color: #fbbf24; }
            QPushButton#vcwBtnMajor:pressed { background: #fcd34d; border-color: #f59e0b; }
            /* Status bar */
            QStatusBar { background: #f8fafc; color: #475569; font-size: 14px; border-top: 1px solid #e2e8f0; }
            QStatusBar::item { border: none; }
            /* Count label */
            QLabel#countLabel { color: #94a3b8; font-size: 14px; }
            /* Status bar version widgets */
            QLabel#footerVersion  { color: #475569; font-size: 13px; }
            QLabel#footerSep      { color: #94a3b8; font-size: 13px; }
            QLabel#footerNvmrc    { color: #64748b; font-size: 13px; font-weight: 600; }
            QLabel#footerNvmrcWarn {
                color: #d97706; font-size: 13px; font-weight: 600;
            }
            /* Settings page */
            QWidget#settingsHeader {
                background: #ffffff; border-bottom: 1px solid #e2e8f0;
            }
            QLabel#settingsTitle { font-size: 18px; font-weight: 700; color: #0f172a; }
            QPushButton#settingsBackBtn {
                background: transparent; color: #3b82f6; border: none;
                font-weight: 600; padding: 4px 8px; border-radius: 5px;
            }
            QPushButton#settingsBackBtn:hover   { background: #eff6ff; color: #2563eb; }
            QPushButton#settingsBackBtn:pressed { background: #dbeafe; color: #1d4ed8; }
            QWidget#settingsSidebar { background: #f8fafc; }
            QFrame#settingsDivider  { color: #e2e8f0; background: #e2e8f0; }
            QPushButton#settingsNavItem {
                background: transparent; color: #64748b; border: none;
                border-radius: 6px; padding: 0 12px; font-weight: 500;
                text-align: left;
            }
            QPushButton#settingsNavItem:hover   { background: #f1f5f9; color: #334155; }
            QPushButton#settingsNavItemActive {
                background: #eff6ff; color: #2563eb; border: none;
                border-radius: 6px; padding: 0 12px; font-weight: 600;
                text-align: left;
            }
            QLabel#settingsPanelTitle    { font-size: 20px; font-weight: 700; color: #0f172a; }
            QLabel#settingsPanelSubtitle { font-size: 15px; font-weight: 600; color: #334155; }
            QLabel#settingsPanelHint     { color: #64748b; font-size: 14px; }
            QFrame#settingsPanelDivider  { color: #e2e8f0; background: #e2e8f0; max-height: 1px; border: none; }
            QFrame#flashMessage {
                background: #16a34a; border-radius: 20px;
            }
            QLabel#flashLabel {
                color: #ffffff; font-weight: 600; font-size: 14px;
                background: transparent;
            }
            QPushButton#spinStepBtn {
                background: #f1f5f9; color: #334155;
                border: 1.5px solid #e2e8f0; border-radius: 6px;
                font-size: 18px; font-weight: 600; padding: 0;
            }
            QPushButton#spinStepBtn:hover   { background: #e2e8f0; border-color: #94a3b8; }
            QPushButton#spinStepBtn:pressed { background: #cbd5e1; }
            QPushButton#btnClearCache {
                background: #ffffff; color: #ef4444;
                border: 1.5px solid #fca5a5; border-radius: 6px;
                padding: 5px 14px; font-weight: 500;
            }
            QPushButton#btnClearCache:hover   { background: #fee2e2; border-color: #f87171; }
            QPushButton#btnClearCache:pressed { background: #fecaca; border-color: #ef4444; }
            /* Settings dialog (kept for QGroupBox / QSpinBox shared styles) */
            QDialog { background: #f8fafc; }
            QGroupBox {
                font-weight: 600; color: #334155; border: 1px solid #e2e8f0;
                border-radius: 8px; margin-top: 10px; padding-top: 8px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #64748b; font-size: 14px; }
            QFrame#themeCard {
                background: #ffffff; border: 1.5px solid #e2e8f0; border-radius: 8px;
            }
            QFrame#themeCard:hover { border-color: #94a3b8; }
            QFrame#themeCardSelected {
                background: #eff6ff; border: 2px solid #3b82f6; border-radius: 8px;
            }
            QLabel#themeCardLabel         { color: #64748b; font-size: 12px; }
            QLabel#themeCardLabelSelected { color: #2563eb; font-size: 12px; font-weight: 600; }
            QSpinBox {
                border: 2px solid #e2e8f0; border-radius: 6px; padding: 5px 10px;
                background: #ffffff; color: #334155; min-height: 32px;
            }
            QSpinBox:focus { border-color: #3b82f6; }
            QDialogButtonBox QPushButton {
                background: #f1f5f9; color: #334155; border: 1px solid #e2e8f0;
                border-radius: 6px; padding: 6px 18px; font-weight: 500;
                min-width: 72px; min-height: 30px;
            }
            QDialogButtonBox QPushButton:hover { background: #e2e8f0; }
            QDialogButtonBox QPushButton[text="OK"] { background: #3b82f6; color: #ffffff; border-color: #3b82f6; }
            QDialogButtonBox QPushButton[text="OK"]:hover { background: #2563eb; }
        """).replace("§CHECK§", _CHECK_ICON
           ).replace("§CB_C§",  _CB_CHECKED)

    @staticmethod
    def _dark_stylesheet() -> str:
        return ("""
            * { font-size: 15px; }
            QLabel { color: #cbd5e1; }
            QMainWindow, QStackedWidget { background: #0f172a; }
            QWidget#centralContent { background: #0f172a; }
            QToolTip {
                background: #1e293b; color: #e2e8f0;
                border: 1px solid #334155; border-radius: 6px;
                padding: 4px 8px; font-size: 13px;
            }
            /* Toolbar */
            QToolBar {
                background: #1e293b;
                border: none;
                border-bottom: 1px solid #334155;
                padding: 4px 10px;
                spacing: 2px;
            }
            QToolBar::separator { background: #334155; width: 1px; margin: 5px 6px; }
            QToolBar QToolButton {
                color: #cbd5e1; border: none; border-radius: 6px; padding: 6px 12px;
            }
            QToolBar QToolButton:hover   { background: #334155; }
            QToolBar QToolButton:pressed { background: #475569; }
            QToolBar QToolButton[text="✕  Close"]         { color: #f87171; }
            QToolBar QToolButton[text="✕  Close"]:hover   { background: #450a0a; color: #fca5a5; }
            QToolBar QToolButton[text="✕  Close"]:pressed { background: #7f1d1d; color: #fecaca; }
            QLabel#fileLabel { color: #475569; font-size: 13px; padding: 0 8px; }
            /* Filter bar */
            QFrame#filterBar {
                background: #1e293b; border: 1px solid #334155; border-radius: 8px;
            }
            QLabel#showLabel { color: #64748b; font-weight: 600; font-size: 14px; }
            /* Start screen */
            QWidget#startScreen  { background: transparent; }
            QLabel#startIcon     { font-size: 48px; }
            QLabel#startTitle    { font-size: 24px; font-weight: 700; color: #f1f5f9; }
            QLabel#startSubtitle { font-size: 15px; color: #64748b; }
            QPushButton#startBtnPrimary {
                background: #3b82f6; color: #ffffff; border: none;
                border-radius: 8px; padding: 10px 22px; font-weight: 600; min-width: 170px;
            }
            QPushButton#startBtnPrimary:hover   { background: #2563eb; }
            QPushButton#startBtnPrimary:pressed { background: #1d4ed8; }
            QPushButton#startBtnSecondary {
                background: #1e293b; color: #cbd5e1;
                border: 1.5px solid #334155; border-radius: 8px;
                padding: 10px 22px; font-weight: 600; min-width: 140px;
            }
            QPushButton#startBtnSecondary:hover   { background: #334155; border-color: #475569; }
            QPushButton#startBtnSecondary:pressed { background: #475569; }
            QLabel#recentHeader { font-size: 13px; font-weight: 700; color: #475569; letter-spacing: 1px; }
            QPushButton#recentClearBtn {
                background: transparent; color: #475569; border: none;
                font-size: 13px; font-weight: 600; padding: 0 2px;
            }
            QPushButton#recentClearBtn:hover   { color: #ef4444; }
            QPushButton#recentClearBtn:pressed { color: #dc2626; }
            QFrame#recentRow { background: #1e293b; border: 1px solid #334155; border-radius: 10px; }
            QFrame#recentRow:hover { background: #1e3a5f; border-color: #3b82f6; }
            QLabel#recentName { font-size: 15px; font-weight: 600; color: #e2e8f0; }
            QLabel#recentPath { font-size: 13px; color: #475569; }
            QLabel#recentAge  { font-size: 13px; color: #475569; }
            QPushButton#recentRemoveBtn {
                background: transparent; color: #334155; border: none;
                font-size: 16px; border-radius: 4px; padding: 0;
            }
            QPushButton#recentRemoveBtn:hover   { background: #450a0a; color: #ef4444; }
            QPushButton#recentRemoveBtn:pressed { background: #7f1d1d; color: #fca5a5; }
            QLabel#noRecent   { font-size: 15px; color: #475569; padding: 20px; }
            /* Table */
            QFrame#tableFrame {
                border: 1px solid #334155;
                border-radius: 10px;
            }
            QTableWidget {
                border: none; border-radius: 0; background: #1e293b;
                gridline-color: transparent; outline: none;
                selection-background-color: transparent; alternate-background-color: #172032;
            }
            QTableWidget::item { padding: 0 10px; border-bottom: 1px solid #1e293b; color: #e2e8f0; }
            QTableWidget::item:selected           { background: #1e3a5f; color: #e2e8f0; }
            QTableWidget::item:alternate          { background: #172032; }
            QTableWidget::item:alternate:selected { background: #1e3a5f; }
            QHeaderView { border: none; }
            QHeaderView::section {
                background: #0f172a; color: #475569; font-size: 13px; font-weight: 700;
                border: none; border-bottom: 1px solid #334155; padding: 8px 10px;
            }
            QHeaderView::section:first { border-top-left-radius: 9px; }
            QHeaderView::section:last  { border-top-right-radius: 9px; }
            QLabel#pkgName { color: #e2e8f0; background: transparent; }
            QPushButton#pkgLinkBtn {
                background: #1e3a5f; border: 1px solid #2563eb;
                color: #93c5fd; font-size: 12px; font-weight: 600;
                border-radius: 4px; padding: 0 7px;
            }
            QPushButton#pkgLinkBtn:hover   { background: #1d4ed8; border-color: #3b82f6; color: #ffffff; }
            QPushButton#pkgLinkBtn:pressed { background: #1e40af; border-color: #60a5fa; color: #ffffff; }
            QLabel#pkgPendingChip {
                background: #451a03; color: #fcd34d;
                border: 1px solid #b45309; border-radius: 4px;
                font-size: 12px; font-weight: 600; padding: 0 7px;
            }
            /* Scrollbars */
            QScrollBar:vertical   { background: transparent; width: 8px;  margin: 4px 2px; }
            QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px 4px; }
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
                background: #334155; border-radius: 4px; min-height: 28px; min-width: 28px;
            }
            QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: #475569; }
            QScrollBar::add-line:vertical,  QScrollBar::sub-line:vertical  { height: 0; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
            QTableCornerButton::section {
                background: #0f172a; border: none;
                border-bottom: 1px solid #334155; border-right: 1px solid #334155;
            }
            /* ComboBox */
            QComboBox {
                border: 1px solid #334155; border-radius: 6px; padding: 5px 10px;
                background: #1e293b; color: #e2e8f0; min-height: 30px;
                selection-background-color: #1e3a5f;
            }
            QComboBox:hover { border-color: #475569; }
            QComboBox:focus { border-color: #3b82f6; }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView {
                border: 1px solid #334155; background: #1e293b; outline: none;
                selection-background-color: #1e3a5f; selection-color: #e2e8f0;
            }
            /* CheckBox */
            QCheckBox { color: #cbd5e1; spacing: 7px; }
            QCheckBox::indicator {
                width: 16px; height: 16px; border: 2px solid #475569;
                border-radius: 4px; background: #1e293b;
            }
            QCheckBox::indicator:hover   { border-color: #64748b; }
            QCheckBox::indicator:checked { background: #3b82f6; border-color: #3b82f6; image: url(§CHECK§); }
            /* Table row checkbox — 20×20 QPushButton centred in a transparent container */
            QPushButton#tableCheckbox {
                background: transparent; border: 2px solid #94a3b8;
                border-radius: 4px; padding: 0;
            }
            QPushButton#tableCheckbox:hover    { border-color: #cbd5e1; }
            QPushButton#tableCheckbox:checked  { background: #3b82f6; border-color: #3b82f6; image: url(§CB_C§); }
            QPushButton#tableCheckbox:disabled { border-color: #334155; }
            /* Action bar */
            QFrame#actionSep { color: #334155; background: #334155; max-height: 1px; border: none; }
            QPushButton#btnBlue {
                background: #3b82f6; color: #ffffff; border: none;
                border-radius: 7px; padding: 7px 18px; font-weight: 600; min-height: 32px;
            }
            QPushButton#btnBlue:hover     { background: #2563eb; }
            QPushButton#btnBlue:pressed   { background: #1d4ed8; }
            QPushButton#btnBlue:disabled  { background: #1e3a8a; }
            QPushButton#btnPurple {
                background: #8b5cf6; color: #ffffff; border: none;
                border-radius: 7px; padding: 7px 18px; font-weight: 600; min-height: 32px;
            }
            QPushButton#btnPurple:hover    { background: #7c3aed; }
            QPushButton#btnPurple:pressed  { background: #6d28d9; }
            QPushButton#btnPurple:disabled { background: #3b0764; }
            QPushButton#btnUpdateAllMain {
                background: #8b5cf6; color: #ffffff; border: none;
                border-top-left-radius: 7px; border-bottom-left-radius: 7px;
                border-top-right-radius: 0; border-bottom-right-radius: 0;
                padding: 7px 14px; font-weight: 600; min-height: 32px;
            }
            QPushButton#btnUpdateAllMain:hover   { background: #7c3aed; }
            QPushButton#btnUpdateAllMain:pressed { background: #6d28d9; }
            QPushButton#btnUpdateAllMain:disabled { background: #3b0764; color: #6d28d9; }
            QPushButton#btnUpdateAllArrow {
                background: #8b5cf6; color: #ffffff; border: none;
                border-top-right-radius: 7px; border-bottom-right-radius: 7px;
                border-top-left-radius: 0; border-bottom-left-radius: 0;
                border-left: 1px solid #6d28d9;
                padding: 0; font-size: 14px; min-height: 32px;
            }
            QPushButton#btnUpdateAllArrow:hover   { background: #7c3aed; }
            QPushButton#btnUpdateAllArrow:pressed { background: #6d28d9; }
            QPushButton#btnUpdateAllArrow:disabled { background: #3b0764; color: #4c1d95; border-left-color: #4c1d95; }
            QPushButton#btnDanger {
                background: #ef4444; color: #ffffff; border: none;
                border-radius: 7px; padding: 7px 18px; font-weight: 600; min-height: 32px;
            }
            QPushButton#btnDanger:hover   { background: #dc2626; }
            QPushButton#btnDanger:pressed { background: #b91c1c; }
            QPushButton#btnGhost {
                background: transparent; color: #94a3b8;
                border: 1.5px solid #334155; border-radius: 7px;
                padding: 7px 18px; font-weight: 500; min-height: 32px;
            }
            QPushButton#btnGhost:hover   { background: #1e293b; border-color: #475569; }
            QPushButton#btnGhost:pressed { background: #334155; }
            /* Progress */
            QProgressBar { border: none; border-radius: 3px; background: #334155; max-height: 6px; }
            QProgressBar::chunk {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #3b82f6, stop:1 #60a5fa);
                border-radius: 3px;
            }
            /* npm install button */
            QPushButton#btnNpmInstall {
                background: #1e293b; color: #cbd5e1;
                border: 1.5px solid #334155; border-radius: 7px;
                padding: 7px 18px; font-weight: 600; min-height: 32px;
            }
            QPushButton#btnNpmInstall:hover    { background: #334155; border-color: #475569; }
            QPushButton#btnNpmInstall:pressed  { background: #475569; }
            QPushButton#btnNpmInstall:disabled { background: #0f172a; color: #334155; border-color: #1e293b; }
            /* npm install modal */
            QFrame#npmCard {
                background: #1e293b; border-radius: 12px;
                border: 1px solid #334155;
            }
            QLabel#npmCardTitle { font-size: 18px; font-weight: 600; color: #f1f5f9; }
            QLabel#npmStatusRunning { color: #94a3b8; font-size: 15px; }
            QLabel#npmStatusOk      { color: #4ade80; font-size: 15px; font-weight: 600; }
            QLabel#npmStatusError   { color: #f87171; font-size: 15px; font-weight: 600; }
            QPushButton#npmToggle {
                background: #1e293b; color: #64748b;
                border: 1px solid #334155; border-radius: 6px;
                padding: 6px 12px; font-size: 14px; font-weight: 600;
                text-align: left;
            }
            QPushButton#npmToggle:hover   { background: #334155; color: #94a3b8; }
            QPushButton#npmToggle:checked { background: #334155; color: #94a3b8; }
            QTextEdit#npmOutput {
                background: #020617; color: #e2e8f0;
                border: 1px solid #334155; border-radius: 6px;
                selection-background-color: #334155;
            }
            /* Version cell widgets */
            QLabel#tableEmptyMsg { color: #475569; font-size: 15px; background: transparent; }
            QLabel#vcwLoading { color: #475569; font-style: italic; font-size: 14px; }
            QLabel#vcwError   { color: #f87171; font-size: 14px; }
            QLabel#vcwNone    { color: #334155; font-size: 16px; }
            QLabel#vcwVersion { color: #e2e8f0; font-size: 14px; font-weight: 600; }
            QLabel#vcwAge     { color: #94a3b8; font-size: 13px; }
            QPushButton#vcwBtnPatch {
                background: #1e3a5f; color: #93c5fd;
                border: 1.5px solid #2563eb; border-radius: 6px;
                font-size: 16px; font-weight: 700;
            }
            QPushButton#vcwBtnPatch:hover   { background: #1d4ed8; border-color: #3b82f6; color: #ffffff; }
            QPushButton#vcwBtnPatch:pressed { background: #1e40af; border-color: #60a5fa; color: #ffffff; }
            QPushButton#vcwBtnMinor {
                background: #14532d; color: #86efac;
                border: 1.5px solid #16a34a; border-radius: 6px;
                font-size: 16px; font-weight: 700;
            }
            QPushButton#vcwBtnMinor:hover   { background: #15803d; border-color: #22c55e; color: #ffffff; }
            QPushButton#vcwBtnMinor:pressed { background: #166534; border-color: #4ade80; color: #ffffff; }
            QPushButton#vcwBtnMajor {
                background: #451a03; color: #fcd34d;
                border: 1.5px solid #b45309; border-radius: 6px;
                font-size: 16px; font-weight: 700;
            }
            QPushButton#vcwBtnMajor:hover   { background: #92400e; border-color: #d97706; color: #ffffff; }
            QPushButton#vcwBtnMajor:pressed { background: #78350f; border-color: #f59e0b; color: #ffffff; }
            /* Status bar */
            QStatusBar { background: #0f172a; color: #94a3b8; font-size: 14px; border-top: 1px solid #334155; }
            QStatusBar::item { border: none; }
            /* Count label */
            QLabel#countLabel { color: #475569; font-size: 14px; }
            /* Status bar version widgets */
            QLabel#footerVersion  { color: #94a3b8; font-size: 13px; }
            QLabel#footerSep      { color: #475569; font-size: 13px; }
            QLabel#footerNvmrc    { color: #64748b; font-size: 13px; font-weight: 600; }
            QLabel#footerNvmrcWarn {
                color: #f59e0b; font-size: 13px; font-weight: 600;
            }
            /* Settings page */
            QWidget#settingsHeader {
                background: #1e293b; border-bottom: 1px solid #334155;
            }
            QLabel#settingsTitle { font-size: 18px; font-weight: 700; color: #f1f5f9; }
            QPushButton#settingsBackBtn {
                background: transparent; color: #60a5fa; border: none;
                font-weight: 600; padding: 4px 8px; border-radius: 5px;
            }
            QPushButton#settingsBackBtn:hover   { background: #1e3a5f; color: #93c5fd; }
            QPushButton#settingsBackBtn:pressed { background: #1e3a8a; color: #bfdbfe; }
            QWidget#settingsSidebar { background: #1e293b; }
            QFrame#settingsDivider  { color: #334155; background: #334155; }
            QPushButton#settingsNavItem {
                background: transparent; color: #94a3b8; border: none;
                border-radius: 6px; padding: 0 12px; font-weight: 500;
                text-align: left;
            }
            QPushButton#settingsNavItem:hover   { background: #334155; color: #cbd5e1; }
            QPushButton#settingsNavItemActive {
                background: #1e3a5f; color: #60a5fa; border: none;
                border-radius: 6px; padding: 0 12px; font-weight: 600;
                text-align: left;
            }
            QLabel#settingsPanelTitle    { font-size: 20px; font-weight: 700; color: #f1f5f9; }
            QLabel#settingsPanelSubtitle { font-size: 15px; font-weight: 600; color: #cbd5e1; }
            QLabel#settingsPanelHint     { color: #64748b; font-size: 14px; }
            QFrame#settingsPanelDivider  { color: #334155; background: #334155; max-height: 1px; border: none; }
            QFrame#flashMessage {
                background: #15803d; border-radius: 20px;
            }
            QLabel#flashLabel {
                color: #ffffff; font-weight: 600; font-size: 14px;
                background: transparent;
            }
            QPushButton#spinStepBtn {
                background: #1e293b; color: #e2e8f0;
                border: 1.5px solid #334155; border-radius: 6px;
                font-size: 18px; font-weight: 600; padding: 0;
            }
            QPushButton#spinStepBtn:hover   { background: #334155; border-color: #475569; }
            QPushButton#spinStepBtn:pressed { background: #475569; }
            QPushButton#btnClearCache {
                background: #1e293b; color: #f87171;
                border: 1.5px solid #7f1d1d; border-radius: 6px;
                padding: 5px 14px; font-weight: 500;
            }
            QPushButton#btnClearCache:hover   { background: #450a0a; border-color: #ef4444; }
            QPushButton#btnClearCache:pressed { background: #7f1d1d; border-color: #f87171; }
            /* Settings dialog (kept for QGroupBox / QSpinBox shared styles) */
            QDialog { background: #0f172a; }
            QGroupBox {
                font-weight: 600; color: #cbd5e1; border: 1px solid #334155;
                border-radius: 8px; margin-top: 10px; padding-top: 8px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #64748b; font-size: 14px; }
            QFrame#themeCard {
                background: #1e293b; border: 1.5px solid #334155; border-radius: 8px;
            }
            QFrame#themeCard:hover { border-color: #475569; }
            QFrame#themeCardSelected {
                background: #172554; border: 2px solid #3b82f6; border-radius: 8px;
            }
            QLabel#themeCardLabel         { color: #64748b; font-size: 12px; }
            QLabel#themeCardLabelSelected { color: #60a5fa; font-size: 12px; font-weight: 600; }
            QSpinBox {
                border: 2px solid #334155; border-radius: 6px; padding: 5px 10px;
                background: #1e293b; color: #e2e8f0; min-height: 32px;
            }
            QSpinBox:focus { border-color: #3b82f6; }
            QDialogButtonBox QPushButton {
                background: #1e293b; color: #cbd5e1; border: 1px solid #334155;
                border-radius: 6px; padding: 6px 18px; font-weight: 500;
                min-width: 72px; min-height: 30px;
            }
            QDialogButtonBox QPushButton:hover { background: #334155; }
            QDialogButtonBox QPushButton[text="OK"] { background: #3b82f6; color: #ffffff; border-color: #3b82f6; }
            QDialogButtonBox QPushButton[text="OK"]:hover { background: #2563eb; }
        """).replace("§CHECK§", _CHECK_ICON
           ).replace("§CB_C§",  _CB_CHECKED)
