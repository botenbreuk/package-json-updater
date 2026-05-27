"""
Custom QStyledItemDelegate that renders version cells with colour coding
and a clickable-button appearance.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QRect, QSize, QModelIndex
from PyQt6.QtGui import QPainter, QColor, QFont
from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle

# ── item data roles ───────────────────────────────────────────────────────────
ROLE_VERSION   = Qt.ItemDataRole.UserRole          # str | None
ROLE_BUMP_TYPE = Qt.ItemDataRole.UserRole + 1      # 'patch' | 'minor' | 'major' | None
ROLE_IS_PENDING = Qt.ItemDataRole.UserRole + 2     # bool
ROLE_AGE       = Qt.ItemDataRole.UserRole + 3      # int | None  (days since published)
ROLE_STATUS    = Qt.ItemDataRole.UserRole + 4      # 'loading' | 'error' | 'ok' | 'none'

# ── colours ───────────────────────────────────────────────────────────────────
_PILL_COLORS = {
    "patch":   QColor("#22c55e"),   # green-500
    "minor":   QColor("#f59e0b"),   # amber-500
    "major":   QColor("#ef4444"),   # red-500
    "none":    QColor("#d1d5db"),   # gray-300
    "loading": QColor("#e5e7eb"),   # gray-200
    "error":   QColor("#fecaca"),   # red-100
}
_PENDING_BORDER = QColor("#2563eb")  # blue-600
_WHITE          = QColor("#ffffff")
_GRAY           = QColor("#6b7280")  # gray-500
_RED_TEXT       = QColor("#b91c1c")  # red-700
_SEL_BG         = QColor("#eff6ff")  # blue-50  — keeps pills readable on selected rows

_RADIUS = 8


class VersionDelegate(QStyledItemDelegate):
    """Renders a version string as a pill-shaped badge with optional age sub-text."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._dark: bool = False

    def set_dark(self, dark: bool) -> None:
        self._dark = dark

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        painter.save()

        status: str      = index.data(ROLE_STATUS) or "none"
        version: str | None = index.data(ROLE_VERSION)
        bump_type: str | None = index.data(ROLE_BUMP_TYPE)
        is_pending: bool = bool(index.data(ROLE_IS_PENDING))
        age: int | None  = index.data(ROLE_AGE)

        rect = option.rect  # type: ignore[attr-defined]

        # Theme-dependent colours
        if self._dark:
            sel_bg       = QColor("#1e3a5f")
            loading_bg   = QColor("#334155")
            loading_fg   = QColor("#64748b")
            error_bg     = QColor("#7f1d1d")
            error_fg     = QColor("#fca5a5")
            dash_fg      = QColor("#475569")
        else:
            sel_bg       = _SEL_BG
            loading_bg   = _PILL_COLORS["loading"]
            loading_fg   = _GRAY
            error_bg     = _PILL_COLORS["error"]
            error_fg     = _RED_TEXT
            dash_fg      = _GRAY

        # Subtle selection highlight so pills stay legible on selected rows.
        if option.state & QStyle.StateFlag.State_Selected:  # type: ignore[attr-defined]
            painter.fillRect(rect, sel_bg)

        pill = _pill_rect(rect)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── loading ────────────────────────────────────────────────────────────
        if status == "loading":
            painter.setBrush(loading_bg)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(pill, _RADIUS, _RADIUS)
            painter.setPen(loading_fg)
            painter.setFont(_font(9))
            painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, "…")
            painter.restore()
            return

        # ── error ──────────────────────────────────────────────────────────────
        if status == "error":
            painter.setBrush(error_bg)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(pill, _RADIUS, _RADIUS)
            painter.setPen(error_fg)
            painter.setFont(_font(9, bold=True))
            painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, "✕")
            painter.restore()
            return

        # ── no update available ────────────────────────────────────────────────
        if not version:
            painter.setPen(dash_fg)
            painter.setFont(_font(11))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "—")
            painter.restore()
            return

        # ── version pill ───────────────────────────────────────────────────────
        color = _PILL_COLORS.get(bump_type or "none", _PILL_COLORS["none"])
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(pill, _RADIUS, _RADIUS)

        # Pending: draw blue outline *inside* the pill so it isn't clipped.
        if is_pending:
            pen = painter.pen()
            pen.setColor(_PENDING_BORDER)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(pill.adjusted(1, 1, -1, -1), _RADIUS - 1, _RADIUS - 1)

        if age is not None:
            # Two-line layout: version text on top, age hint below.
            split = pill.height() * 58 // 100
            ver_rect = QRect(pill.left(), pill.top(), pill.width(), split)
            age_rect = QRect(pill.left(), pill.top() + split,
                             pill.width(), pill.height() - split)

            painter.setPen(_WHITE)
            painter.setFont(_font(9, bold=is_pending))
            painter.drawText(
                ver_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                version,
            )

            age_color = QColor(_WHITE)
            age_color.setAlpha(210)
            painter.setPen(age_color)
            painter.setFont(_font(7))
            painter.drawText(
                age_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                _fmt_age(age),
            )
        else:
            painter.setPen(_WHITE)
            painter.setFont(_font(9, bold=is_pending))
            painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, version)

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(120, 52)


# ── helpers ───────────────────────────────────────────────────────────────────

def _pill_rect(cell_rect: QRect) -> QRect:
    """Return a padded rect centred inside *cell_rect* for the pill."""
    return cell_rect.adjusted(10, 6, -10, -6)


def _font(pt: int, bold: bool = False) -> QFont:
    f = QFont()
    f.setPointSize(pt)
    f.setBold(bold)
    return f


def _fmt_age(days: int) -> str:
    """Human-friendly age string: '14d', '3mo', '2y'."""
    if days < 30:
        return f"{days}d"
    if days < 365:
        return f"{days // 30}mo"
    return f"{days // 365}y"
