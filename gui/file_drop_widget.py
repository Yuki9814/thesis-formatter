from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLineEdit


class FileDropLineEdit(QLineEdit):
    fileDropped = Signal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):  # noqa: N802 - Qt API
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):  # noqa: N802 - Qt API
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            self.setText(path)
            self.fileDropped.emit(path)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

