from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLineEdit


class FileDropLineEdit(QLineEdit):
    fileDropped = Signal(str)

    def __init__(self, *args, allowed_suffixes: set[str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.allowed_suffixes = {item.lower() for item in (allowed_suffixes or {".docx"})}
        self.setAcceptDrops(True)

    def _accepted_path(self, event) -> str | None:
        urls = event.mimeData().urls()
        if not urls:
            return None
        path = urls[0].toLocalFile()
        if not path:
            return None
        if Path(path).suffix.lower() not in self.allowed_suffixes:
            return None
        return path

    def dragEnterEvent(self, event):  # noqa: N802 - Qt API
        if event.mimeData().hasUrls() and self._accepted_path(event):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):  # noqa: N802 - Qt API
        path = self._accepted_path(event)
        if path:
            self.setText(path)
            self.fileDropped.emit(path)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
