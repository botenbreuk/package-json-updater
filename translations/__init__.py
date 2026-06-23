from __future__ import annotations

from PyQt6.QtCore import QTranslator


class DictTranslator(QTranslator):
    """QTranslator backed by a plain Python dict — no compiled .qm file needed."""

    def __init__(self, translations: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self._t = translations

    def translate(self, context: str, source_text: str,
                  disambiguation: str | None = None, n: int = -1) -> str:
        return self._t.get(source_text, source_text)
