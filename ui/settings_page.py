"""
Settings page — lives in the main QStackedWidget (not a dialog).

Signals
-------
settings_changed(AppSettings)
    Emitted when the user clicks Save with valid settings.
back_requested()
    Emitted when the user clicks ← Back (with or without saving).
cache_clear_requested()
    Emitted when the user clicks "Clear Cache Now".
"""
from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QRect, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QFrame, QGraphicsOpacityEffect, QGroupBox,
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QSpinBox,
    QStackedWidget, QVBoxLayout, QWidget,
)

from models.settings import AppSettings


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
    settings_changed    = pyqtSignal(object)   # AppSettings
    back_requested      = pyqtSignal()
    cache_clear_requested = pyqtSignal()

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._build_ui()

    # ── public API ────────────────────────────────────────────────────────────

    def refresh(self, settings: AppSettings) -> None:
        """Sync the form to *settings* before the page is shown."""
        self._settings = settings
        self._age_spin.setValue(settings.min_age_days)
        self._ttl_spin.setValue(settings.cache_ttl_hours)
        self._select_theme(settings.theme)
        for scroll in self._panel_scrolls:
            scroll.verticalScrollBar().setValue(0)

    # ── construction ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── header ────────────────────────────────────────────────────────────
        header = QWidget()
        header.setObjectName("settingsHeader")
        h_row = QHBoxLayout(header)
        h_row.setContentsMargins(16, 10, 16, 10)
        h_row.setSpacing(12)

        back_btn = QPushButton("← Back")
        back_btn.setObjectName("settingsBackBtn")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(self.back_requested)
        h_row.addWidget(back_btn)

        title = QLabel("Settings")
        title.setObjectName("settingsTitle")
        h_row.addWidget(title)
        h_row.addStretch()
        root.addWidget(header)

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
        for i, label in enumerate(("Theme", "Version Age Filter", "Version Cache")):
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
        theme_scroll  = self._build_theme_panel()
        age_scroll    = self._build_age_panel()
        cache_scroll  = self._build_cache_panel()
        self._content_stack.addWidget(theme_scroll)
        self._content_stack.addWidget(age_scroll)
        self._content_stack.addWidget(cache_scroll)
        self._panel_scrolls = [theme_scroll, age_scroll, cache_scroll]
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
        self._settings.min_age_days    = self._age_spin.value()
        self._settings.cache_ttl_hours = self._ttl_spin.value()
        self._settings.theme           = self._selected_theme
        self._settings.save()
        self.settings_changed.emit(self._settings)
        # Parent to the central widget so the toast outlives this page
        central = self.window().centralWidget()
        _FlashMessage("✓  Settings saved", central or self)
        self.back_requested.emit()

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
        central = self.window().centralWidget()
        _FlashMessage("✓  Cache cleared", central or self)
