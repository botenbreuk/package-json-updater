"""
Settings dialog for configuring minimum version age and other preferences.
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QLabel, QSpinBox, QVBoxLayout, QWidget,
)

from models.settings import AppSettings


class SettingsDialog(QDialog):
    """
    Modal dialog for editing AppSettings.

    Signal
    ------
    settings_changed(AppSettings)
        Emitted when the user clicks OK with valid settings.
    """

    settings_changed = pyqtSignal(object)

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("Settings")
        self.setMinimumWidth(380)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # ── Version age ─────────────────────────────────────────────────────
        age_group = QGroupBox("Version Age Filter")
        age_layout = QFormLayout(age_group)
        age_layout.setSpacing(8)

        self._age_spin = QSpinBox()
        self._age_spin.setRange(0, 365)
        self._age_spin.setValue(self._settings.min_age_days)
        self._age_spin.setSuffix(" days")
        self._age_spin.setSpecialValueText("No filter (0 days)")
        self._age_spin.setToolTip(
            "Only show package versions that have been published for at least this many days.\n"
            "Set to 0 to disable the filter."
        )

        age_layout.addRow("Minimum age:", self._age_spin)
        age_layout.addRow(
            "",
            QLabel(
                "<small style='color:#6b7280'>Helps avoid recently published packages "
                "that might be reverted or have known issues.</small>"
            ),
        )
        layout.addWidget(age_group)

        # ── Dialog buttons ───────────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        self._settings.min_age_days = self._age_spin.value()
        self._settings.save()
        self.settings_changed.emit(self._settings)
        self.accept()
