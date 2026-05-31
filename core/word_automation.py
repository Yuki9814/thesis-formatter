from __future__ import annotations

from pathlib import Path
from typing import Protocol


class WordAutomation(Protocol):
    def update_fields_and_save(self, docx_path: str | Path) -> None:
        ...

    def validate_layout(self, docx_path: str | Path) -> dict:
        ...


class NoopWordAutomation:
    """Reserved interface for future Microsoft Word automation.

    MVP is Mac-developable and does not treat Mac output as final layout
    authority. A later Windows implementation can use pywin32/Word COM here.
    """

    def update_fields_and_save(self, docx_path: str | Path) -> None:
        return None

    def validate_layout(self, docx_path: str | Path) -> dict:
        return {"available": False, "message": "Word automation is not implemented in MVP."}

