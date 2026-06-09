"""
Settings page — lives in the main QStackedWidget (not a dialog).

Signals
-------
settings_changed(AppSettings)
    Emitted when the user clicks Save with valid settings.
cache_clear_requested()
    Emitted when the user clicks "Clear Cache Now".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PyQt6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QRect, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QCheckBox, QComboBox, QFrame, QGraphicsOpacityEffect, QGroupBox,
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QSpinBox,
    QStackedWidget, QVBoxLayout, QWidget,
)

from _version import VERSION
from core.npm_cache import NpmCache
from models.settings import AppSettings


def _fmt_ago(dt: datetime | None) -> str:
    if dt is None:
        return "never"
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    days = int(secs // 86400)
    if days == 1:
        return "yesterday"
    if days < 60:
        return f"{days}d ago"
    if days < 730:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


def _fmt_duration(secs: float) -> str:
    if secs < 3600:
        return f"{int(secs // 60)}m"
    if secs < 86400:
        return f"{int(secs // 3600)}h"
    days = int(secs // 86400)
    if days < 60:
        return f"{days}d"
    if days < 730:
        return f"{days // 30}mo"
    return f"{days // 365}y"


# ── mini theme preview ────────────────────────────────────────────────────────

_LIGHT = dict(
    bg=QColor("#f8fafc"), toolbar=QColor("#ffffff"), border=QColor("#e2e8f0"),
    row_alt=QColor("#f1f5f9"), muted=QColor("#cbd5e1"), accent=QColor("#3b82f6"),
    status=QColor("#f8fafc"),
)
_DARK = dict(
    bg=QColor("#0f172a"), toolbar=QColor("#1e293b"), border=QColor("#334155"),
    row_alt=QColor("#1e293b"), muted=QColor("#334155"), accent=QColor("#3b82f6"),
    status=QColor("#0f172a"),
)


def _paint_preview(painter: QPainter, c: dict, rect: QRect) -> None:
    """Draw a miniature UI using colour palette *c* clipped to *rect*.

    All element sizes are derived from *w* and *h* so the painting scales
    correctly regardless of the widget size.
    """
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    p = painter
    p.setPen(Qt.PenStyle.NoPen)

    # Background
    p.setBrush(c["bg"])
    p.drawRoundedRect(rect, 6, 6)

    # ── Toolbar ───────────────────────────────────────────────────────────────
    th = max(12, h // 5)
    p.setBrush(c["toolbar"])
    p.drawRect(x, y, w, th)
    p.setBrush(c["border"])
    p.drawRect(x, y + th, w, max(1, h // 80))

    # Fake action buttons — all sizes proportional to toolbar height
    btn_h  = max(3, th // 4)
    btn_w  = max(5, th // 2)
    btn_gap = btn_w + max(4, th // 5)
    btn_y  = y + (th - btn_h) // 2
    p.setBrush(c["muted"])
    for i in range(3):
        p.drawRoundedRect(x + 4 + i * btn_gap, btn_y, btn_w, btn_h, 1, 1)

    # Accent button (right side)
    acc_w = max(8, th * 2 // 3)
    acc_h = max(4, th // 3)
    p.setBrush(c["accent"])
    p.drawRoundedRect(x + w - acc_w - 4, y + (th - acc_h) // 2, acc_w, acc_h, 2, 2)

    # ── Content rows ──────────────────────────────────────────────────────────
    sb        = max(8, h // 8)          # status bar height (computed first)
    cy        = y + th + 2
    available = h - th - 2 - sb
    row_h     = max(6, available // 3)
    bar_h     = max(2, row_h // 5)     # text-stub height scales with row

    for i in range(3):
        p.setBrush(c["row_alt"] if i % 2 else c["bg"])
        p.drawRect(x, cy, w, row_h)
        p.setBrush(c["muted"])
        p.drawRoundedRect(x + 4, cy + (row_h - bar_h) // 2, int(w * 0.44), bar_h, 1, 1)
        p.drawRoundedRect(x + w - int(w * 0.22), cy + (row_h - bar_h) // 2,
                          int(w * 0.17), bar_h, 1, 1)
        cy += row_h

    # ── Status bar ────────────────────────────────────────────────────────────
    p.setBrush(c["toolbar"])
    p.drawRect(x, y + h - sb, w, sb)
    p.setBrush(c["muted"])
    p.drawRoundedRect(x + 4, y + h - sb + (sb - bar_h) // 2,
                      int(w * 0.32), bar_h, 1, 1)


class _NoScrollSpinBox(QSpinBox):
    """QSpinBox that ignores scroll-wheel events so the page scrolls instead."""

    def wheelEvent(self, event) -> None:
        event.ignore()


class _ConfirmOverlay(QWidget):
    """In-app confirmation modal — semi-transparent backdrop with a centred card."""

    confirmed = pyqtSignal()

    def __init__(
        self,
        title: str,
        body: str,
        confirm_label: str = "Confirm",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if parent:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)
        self._build_ui(title, body, confirm_label)
        self.raise_()
        self.show()

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
        return super().eventFilter(obj, event)

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        QPainter(self).fillRect(self.rect(), QColor(0, 0, 0, 140))

    def _build_ui(self, title: str, body: str, confirm_label: str) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)

        card = QFrame()
        card.setObjectName("npmCard")
        card.setFixedWidth(460)
        c = QVBoxLayout(card)
        c.setContentsMargins(28, 24, 28, 24)
        c.setSpacing(12)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("npmCardTitle")
        c.addWidget(title_lbl)

        body_lbl = QLabel(body)
        body_lbl.setObjectName("settingsPanelHint")
        body_lbl.setWordWrap(True)
        c.addWidget(body_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setObjectName("btnGhost")
        cancel.setMinimumWidth(88)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self._close)
        btn_row.addWidget(cancel)

        confirm = QPushButton(confirm_label)
        confirm.setObjectName("btnDanger")
        confirm.setMinimumWidth(88)
        confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm.clicked.connect(self._on_confirm)
        btn_row.addWidget(confirm)

        c.addLayout(btn_row)
        outer.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)

    def _on_confirm(self) -> None:
        self.confirmed.emit()
        self._close()

    def _close(self) -> None:
        if self.parent():
            self.parent().removeEventFilter(self)
        self.hide()
        self.deleteLater()


class _FlashMessage(QFrame):
    """Floating toast that fades out automatically.

    Centres itself at the top of *parent*, stays fully opaque for
    ``show_ms`` milliseconds then fades out over ``fade_ms`` milliseconds.
    Deletes itself when the animation finishes.  Parent should be the
    main window's central widget so the toast survives page navigation.
    """

    def __init__(
        self,
        text: str,
        parent: QWidget,
        show_ms: int = 800,
        fade_ms: int = 450,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("flashMessage")

        lo = QHBoxLayout(self)
        lo.setContentsMargins(20, 10, 20, 10)
        lbl = QLabel(text)
        lbl.setObjectName("flashLabel")
        lo.addWidget(lbl)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)

        self.adjustSize()
        self._reposition()
        self.raise_()
        self.show()

        QTimer.singleShot(show_ms, self._start_fade)
        self._fade_ms = fade_ms

    def _reposition(self) -> None:
        p = self.parent()
        if p:
            self.move((p.width() - self.width()) // 2, 16)

    def _start_fade(self) -> None:
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(self._fade_ms)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self.deleteLater)
        self._anim.start()


class _MiniPreview(QWidget):
    """Paints a small screenshot-style representation of a theme."""

    def __init__(self, value: str, parent=None) -> None:
        super().__init__(parent)
        self._value = value
        self.setFixedSize(190, 110)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRect(0, 0, self.width(), self.height())

        if self._value == "system":
            # Left half: light theme; right half: dark — diagonal boundary
            _paint_preview(p, _LIGHT, rect)
            path = QPainterPath()
            w, h = self.width(), self.height()
            path.moveTo(w * 0.42, 0)
            path.lineTo(w, 0)
            path.lineTo(w, h)
            path.lineTo(w * 0.58, h)
            path.closeSubpath()
            p.setClipPath(path)
            _paint_preview(p, _DARK, rect)
            p.setClipping(False)
            # Divider line
            p.setPen(QColor("#64748b"))
            p.drawLine(int(w * 0.42), 0, int(w * 0.58), h)
        elif self._value == "dark":
            _paint_preview(p, _DARK, rect)
        else:
            _paint_preview(p, _LIGHT, rect)


# ── theme selection card ──────────────────────────────────────────────────────

class _ThemeCard(QFrame):
    """Clickable card: mini preview + label, highlighted when selected."""

    selected = pyqtSignal(str)   # emits the theme value string

    def __init__(self, value: str, label: str, parent=None) -> None:
        super().__init__(parent)
        self._value = value
        self.setObjectName("themeCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(240)

        lo = QVBoxLayout(self)
        lo.setContentsMargins(18, 12, 18, 0)
        lo.setSpacing(8)

        self._label = QLabel(label)
        self._label.setObjectName("themeCardLabel")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lo.addWidget(self._label)

        self._preview = _MiniPreview(value)
        lo.addWidget(self._preview, 0, Qt.AlignmentFlag.AlignHCenter)

    @property
    def value(self) -> str:
        return self._value

    def set_selected(self, sel: bool) -> None:
        name = "themeCardSelected" if sel else "themeCard"
        label_name = "themeCardLabelSelected" if sel else "themeCardLabel"
        self.setObjectName(name)
        self._label.setObjectName(label_name)
        for w in (self, self._label):
            w.style().unpolish(w)
            w.style().polish(w)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self.selected.emit(self._value)
        super().mousePressEvent(event)


# ── settings page ─────────────────────────────────────────────────────────────

class SettingsPage(QWidget):
    settings_changed      = pyqtSignal(object)   # AppSettings
    cache_clear_requested = pyqtSignal()

    def __init__(self, settings: AppSettings, cache: NpmCache, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._cache = cache
        self._build_ui()

    # ── public API ────────────────────────────────────────────────────────────

    def refresh(self, settings: AppSettings) -> None:
        """Sync the form to *settings* before the page is shown."""
        self._settings = settings
        self._age_spin.setValue(settings.min_age_days)
        self._ttl_spin.setValue(settings.cache_ttl_hours)
        self._old_ver_spin.setValue(settings.old_version_threshold)
        idx = self._old_ver_unit.findData(settings.old_version_unit)
        if idx >= 0:
            self._old_ver_unit.setCurrentIndex(idx)
        self._select_theme(settings.theme)
        self._merge_cb.blockSignals(True)
        self._merge_cb.setChecked(settings.merge_patch_minor)
        self._merge_cb.blockSignals(False)
        for scroll in self._panel_scrolls:
            scroll.verticalScrollBar().setValue(0)
        self._update_cache_status()

    # ── construction ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── body: sidebar + content ───────────────────────────────────────────
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setObjectName("settingsSidebar")
        sidebar.setFixedWidth(190)
        s_layout = QVBoxLayout(sidebar)
        s_layout.setContentsMargins(12, 20, 12, 20)
        s_layout.setSpacing(2)

        self._nav_btns: list[QPushButton] = []
        for i, label in enumerate(("Theme", "Version Age Filter", "Old Version Warning", "Version Cache", "Display", "About")):
            btn = QPushButton(label)
            btn.setObjectName("settingsNavItem")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(34)
            btn.clicked.connect(lambda _checked, idx=i: self._select_nav(idx))
            s_layout.addWidget(btn)
            self._nav_btns.append(btn)

        s_layout.addStretch()
        body_layout.addWidget(sidebar)

        # Divider
        div = QFrame()
        div.setObjectName("settingsDivider")
        div.setFrameShape(QFrame.Shape.VLine)
        div.setFixedWidth(1)
        body_layout.addWidget(div)

        # Content panels
        self._content_stack = QStackedWidget()
        theme_scroll   = self._build_theme_panel()
        age_scroll     = self._build_age_panel()
        old_ver_scroll = self._build_old_version_panel()
        cache_scroll   = self._build_cache_panel()
        display_scroll = self._build_display_panel()
        about_scroll   = self._build_about_panel()
        self._content_stack.addWidget(theme_scroll)
        self._content_stack.addWidget(age_scroll)
        self._content_stack.addWidget(old_ver_scroll)
        self._content_stack.addWidget(cache_scroll)
        self._content_stack.addWidget(display_scroll)
        self._content_stack.addWidget(about_scroll)
        self._panel_scrolls = [theme_scroll, age_scroll, old_ver_scroll, cache_scroll, display_scroll, about_scroll]
        body_layout.addWidget(self._content_stack, 1)

        root.addWidget(body, 1)
        self._select_nav(0)

    def _select_nav(self, index: int) -> None:
        for i, btn in enumerate(self._nav_btns):
            active = i == index
            name = "settingsNavItemActive" if active else "settingsNavItem"
            if btn.objectName() != name:
                btn.setObjectName(name)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
            btn.setChecked(active)
        self._content_stack.setCurrentIndex(index)

    def _build_theme_panel(self) -> QScrollArea:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)

        lbl = QLabel("Theme")
        lbl.setObjectName("settingsPanelTitle")
        layout.addWidget(lbl)

        hint = QLabel("System default follows your OS light/dark preference.")
        hint.setObjectName("settingsPanelHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        self._cards: list[_ThemeCard] = []
        for value, label in (("system", "System default"), ("light", "Light"), ("dark", "Dark")):
            card = _ThemeCard(value, label)
            card.selected.connect(self._on_theme_selected)
            cards_row.addWidget(card)
            self._cards.append(card)
        cards_row.addStretch()
        layout.addLayout(cards_row)
        layout.addStretch()

        self._select_theme(self._settings.theme)
        return self._wrap_scroll(inner)

    def _select_theme(self, value: str) -> None:
        self._selected_theme = value
        for card in self._cards:
            card.set_selected(card.value == value)

    def _on_merge_toggled(self, checked: bool) -> None:
        self._settings.merge_patch_minor = checked
        self._settings.save()
        self.settings_changed.emit(self._settings)
        central = self.window().centralWidget()
        _FlashMessage("✓  Display setting saved", central or self)

    def _on_theme_selected(self, value: str) -> None:
        self._select_theme(value)
        self._settings.theme = value
        self._settings.save()
        self.settings_changed.emit(self._settings)
        central = self.window().centralWidget()
        _FlashMessage("✓  Theme saved", central or self)

    def _build_age_panel(self) -> QScrollArea:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)

        lbl = QLabel("Version Age Filter")
        lbl.setObjectName("settingsPanelTitle")
        layout.addWidget(lbl)

        hint = QLabel(
            "Only show package versions published at least this many days ago. "
            "Helps avoid recently published packages that might be reverted or have known issues. "
            "Set to 0 to disable the filter."
        )
        hint.setObjectName("settingsPanelHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("Minimum age:"))
        row.addStretch(1)

        self._age_spin = _NoScrollSpinBox()
        self._age_spin.setRange(0, 365)
        self._age_spin.setValue(self._settings.min_age_days)
        self._age_spin.setSuffix(" days")
        self._age_spin.setSpecialValueText("No filter (0 days)")
        self._age_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._age_spin.setFixedWidth(155)
        self._age_spin.setToolTip(
            "Only show package versions published at least this many days ago.\n"
            "Set to 0 to disable the filter."
        )

        age_minus = QPushButton("−")
        age_minus.setObjectName("spinStepBtn")
        age_minus.setFixedWidth(32)
        age_minus.setCursor(Qt.CursorShape.PointingHandCursor)
        age_minus.clicked.connect(self._age_spin.stepDown)

        age_plus = QPushButton("+")
        age_plus.setObjectName("spinStepBtn")
        age_plus.setFixedWidth(32)
        age_plus.setCursor(Qt.CursorShape.PointingHandCursor)
        age_plus.clicked.connect(self._age_spin.stepUp)

        row.addWidget(age_minus)
        row.addWidget(self._age_spin)
        row.addWidget(age_plus)
        layout.addLayout(row)

        save_row = QHBoxLayout()
        save_row.addStretch()
        age_save = QPushButton("Save")
        age_save.setObjectName("btnBlue")
        age_save.setMinimumWidth(90)
        age_save.setCursor(Qt.CursorShape.PointingHandCursor)
        age_save.clicked.connect(self._on_save)
        save_row.addWidget(age_save)
        layout.addLayout(save_row)
        layout.addStretch()
        return self._wrap_scroll(inner)

    def _build_old_version_panel(self) -> QScrollArea:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)

        lbl = QLabel("Old Version Warning")
        lbl.setObjectName("settingsPanelTitle")
        layout.addWidget(lbl)

        hint = QLabel(
            "Show a ⚠ warning next to the installed version when it has not been updated "
            "for longer than this threshold. Set to 0 to disable the warning."
        )
        hint.setObjectName("settingsPanelHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("Warn after:"))
        row.addStretch(1)

        self._old_ver_spin = _NoScrollSpinBox()
        self._old_ver_spin.setRange(0, 99)
        self._old_ver_spin.setValue(self._settings.old_version_threshold)
        self._old_ver_spin.setSpecialValueText("Disabled")
        self._old_ver_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._old_ver_spin.setFixedWidth(80)

        old_ver_minus = QPushButton("−")
        old_ver_minus.setObjectName("spinStepBtn")
        old_ver_minus.setFixedWidth(32)
        old_ver_minus.setCursor(Qt.CursorShape.PointingHandCursor)
        old_ver_minus.clicked.connect(self._old_ver_spin.stepDown)

        old_ver_plus = QPushButton("+")
        old_ver_plus.setObjectName("spinStepBtn")
        old_ver_plus.setFixedWidth(32)
        old_ver_plus.setCursor(Qt.CursorShape.PointingHandCursor)
        old_ver_plus.clicked.connect(self._old_ver_spin.stepUp)

        self._old_ver_unit = QComboBox()
        self._old_ver_unit.setObjectName("settingsCombo")
        self._old_ver_unit.addItem("months", "months")
        self._old_ver_unit.addItem("years", "years")
        idx = self._old_ver_unit.findData(self._settings.old_version_unit)
        if idx >= 0:
            self._old_ver_unit.setCurrentIndex(idx)
        self._old_ver_unit.setFixedWidth(90)
        self._old_ver_unit.setCursor(Qt.CursorShape.PointingHandCursor)

        row.addWidget(old_ver_minus)
        row.addWidget(self._old_ver_spin)
        row.addWidget(self._old_ver_unit)
        row.addWidget(old_ver_plus)
        layout.addLayout(row)

        save_row = QHBoxLayout()
        save_row.addStretch()
        old_ver_save = QPushButton("Save")
        old_ver_save.setObjectName("btnBlue")
        old_ver_save.setMinimumWidth(90)
        old_ver_save.setCursor(Qt.CursorShape.PointingHandCursor)
        old_ver_save.clicked.connect(self._on_save)
        save_row.addWidget(old_ver_save)
        layout.addLayout(save_row)
        layout.addStretch()
        return self._wrap_scroll(inner)

    def _build_cache_panel(self) -> QScrollArea:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)

        lbl = QLabel("Version Cache")
        lbl.setObjectName("settingsPanelTitle")
        layout.addWidget(lbl)

        hint = QLabel(
            "Cached results make subsequent opens instant. "
            "Use ↺ Refresh to always get the latest versions regardless of this setting."
        )
        hint.setObjectName("settingsPanelHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._cache_info_lbl = QLabel()
        self._cache_info_lbl.setObjectName("cacheInfoLabel")
        layout.addWidget(self._cache_info_lbl)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("Cache TTL:"))
        row.addStretch(1)

        self._ttl_spin = _NoScrollSpinBox()
        self._ttl_spin.setRange(0, 168)
        self._ttl_spin.setValue(self._settings.cache_ttl_hours)
        self._ttl_spin.setSuffix(" hours")
        self._ttl_spin.setSpecialValueText("Disabled")
        self._ttl_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._ttl_spin.setFixedWidth(155)
        self._ttl_spin.setToolTip(
            "How long fetched version data is reused before going to npm again.\n"
            "Set to 0 to disable caching (always fetch live).\n"
            "The ↺ Refresh button always fetches live regardless of this setting."
        )
        self._ttl_spin.valueChanged.connect(lambda _: self._update_cache_status())

        ttl_minus = QPushButton("−")
        ttl_minus.setObjectName("spinStepBtn")
        ttl_minus.setFixedWidth(32)
        ttl_minus.setCursor(Qt.CursorShape.PointingHandCursor)
        ttl_minus.clicked.connect(self._ttl_spin.stepDown)

        ttl_plus = QPushButton("+")
        ttl_plus.setObjectName("spinStepBtn")
        ttl_plus.setFixedWidth(32)
        ttl_plus.setCursor(Qt.CursorShape.PointingHandCursor)
        ttl_plus.clicked.connect(self._ttl_spin.stepUp)

        row.addWidget(ttl_minus)
        row.addWidget(self._ttl_spin)
        row.addWidget(ttl_plus)
        layout.addLayout(row)

        save_row = QHBoxLayout()
        save_row.addStretch()
        cache_save = QPushButton("Save")
        cache_save.setObjectName("btnBlue")
        cache_save.setMinimumWidth(90)
        cache_save.setCursor(Qt.CursorShape.PointingHandCursor)
        cache_save.clicked.connect(self._on_save)
        save_row.addWidget(cache_save)
        layout.addLayout(save_row)

        # ── divider ───────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setObjectName("settingsPanelDivider")
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # ── clear cache section ───────────────────────────────────────────────
        clear_title = QLabel("Clear Cache")
        clear_title.setObjectName("settingsPanelSubtitle")
        layout.addWidget(clear_title)

        clear_hint = QLabel(
            "Delete all locally stored version data. The next time you open a project "
            "all package information will be re-fetched fresh from the npm registry."
        )
        clear_hint.setObjectName("settingsPanelHint")
        clear_hint.setWordWrap(True)
        layout.addWidget(clear_hint)

        clear_btn = QPushButton("Clear Cache Now")
        clear_btn.setObjectName("btnClearCache")
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setToolTip("Delete all cached npm data immediately.")
        clear_btn.clicked.connect(self._on_clear_cache_clicked)
        layout.addWidget(clear_btn, 0, Qt.AlignmentFlag.AlignLeft)

        self._update_cache_status()
        layout.addStretch()
        return self._wrap_scroll(inner)

    def _build_display_panel(self) -> QScrollArea:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)

        lbl = QLabel("Display")
        lbl.setObjectName("settingsPanelTitle")
        layout.addWidget(lbl)

        hint = QLabel("Customize how version updates are shown in the table.")
        hint.setObjectName("settingsPanelHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        sep = QFrame()
        sep.setObjectName("settingsPanelDivider")
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        merge_title = QLabel("Merge Patch and Minor")
        merge_title.setObjectName("settingsPanelSubtitle")
        layout.addWidget(merge_title)

        merge_hint = QLabel(
            "When enabled, the Patch and Minor columns are merged into one. "
            "The highest available update between the two is shown."
        )
        merge_hint.setObjectName("settingsPanelHint")
        merge_hint.setWordWrap(True)
        layout.addWidget(merge_hint)

        self._merge_cb = QCheckBox("Merge Patch and Minor updates")
        self._merge_cb.setChecked(self._settings.merge_patch_minor)
        self._merge_cb.toggled.connect(self._on_merge_toggled)
        layout.addWidget(self._merge_cb)

        layout.addStretch()
        return self._wrap_scroll(inner)

    def _build_about_panel(self) -> QScrollArea:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)

        lbl = QLabel("About")
        lbl.setObjectName("settingsPanelTitle")
        layout.addWidget(lbl)

        sep = QFrame()
        sep.setObjectName("settingsPanelDivider")
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        name_lbl = QLabel("Package.json Updater")
        name_lbl.setObjectName("settingsPanelSubtitle")
        layout.addWidget(name_lbl)

        version_lbl = QLabel(f"Version {VERSION}")
        version_lbl.setObjectName("settingsPanelHint")
        layout.addWidget(version_lbl)

        layout.addStretch()
        return self._wrap_scroll(inner)

    @staticmethod
    def _wrap_scroll(widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setWidget(widget)
        return scroll

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_save(self) -> None:
        self._settings.min_age_days           = self._age_spin.value()
        self._settings.cache_ttl_hours        = self._ttl_spin.value()
        self._settings.theme                  = self._selected_theme
        self._settings.old_version_threshold  = self._old_ver_spin.value()
        self._settings.old_version_unit       = self._old_ver_unit.currentData()
        self._settings.save()
        self.settings_changed.emit(self._settings)
        central = self.window().centralWidget()
        _FlashMessage("✓  Settings saved", central or self)

    def _on_clear_cache_clicked(self) -> None:
        overlay = _ConfirmOverlay(
            "Clear cache?",
            "All locally stored npm version data will be deleted. "
            "The next time you open a project every package will be re-fetched "
            "from the npm registry, which may take a little longer than usual.",
            confirm_label="Clear Cache",
            parent=self.window(),
        )
        overlay.confirmed.connect(self._do_clear_cache)

    def _do_clear_cache(self) -> None:
        self.cache_clear_requested.emit()
        self._update_cache_status()
        central = self.window().centralWidget()
        _FlashMessage("✓  Cache cleared", central or self)

    def _update_cache_status(self) -> None:
        ttl = self._ttl_spin.value()
        stats = self._cache.stats()
        count = stats["count"]
        newest_at = stats["newest_at"]
        oldest_at = stats["oldest_at"]

        if ttl == 0:
            self._cache_info_lbl.setText("Caching is disabled")
        elif count == 0:
            self._cache_info_lbl.setText("No data cached yet")
        else:
            pkg = "package" if count == 1 else "packages"
            parts = [f"{count} {pkg} cached", f"last updated {_fmt_ago(newest_at)}"]
            if oldest_at is not None:
                expires_at = oldest_at + timedelta(hours=ttl)
                remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
                if remaining <= 0:
                    parts.append("refresh overdue")
                else:
                    parts.append(f"refreshes in {_fmt_duration(remaining)}")
            self._cache_info_lbl.setText(" · ".join(parts))
