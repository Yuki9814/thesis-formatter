from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Dict, Iterable, List


class DocxError(ValueError):
    pass


REQUIRED_PARTS = {"[Content_Types].xml", "word/document.xml"}


def validate_docx_path(path: str | Path) -> Path:
    docx_path = Path(path)
    if not docx_path.exists():
        raise DocxError(f"File does not exist: {docx_path}")
    if docx_path.suffix.lower() != ".docx":
        raise DocxError(f"Only .docx is supported: {docx_path}")
    if not zipfile.is_zipfile(docx_path):
        raise DocxError(f"Not a valid .docx zip package: {docx_path}")
    with zipfile.ZipFile(docx_path) as package:
        names = set(package.namelist())
    missing = REQUIRED_PARTS - names
    if missing:
        raise DocxError(f"Missing required docx parts: {', '.join(sorted(missing))}")
    return docx_path


def read_part(path: str | Path, part_name: str) -> bytes:
    validate_docx_path(path)
    with zipfile.ZipFile(path) as package:
        try:
            return package.read(part_name)
        except KeyError as exc:
            raise DocxError(f"Missing docx part: {part_name}") from exc


def part_exists(path: str | Path, part_name: str) -> bool:
    validate_docx_path(path)
    with zipfile.ZipFile(path) as package:
        return part_name in package.namelist()


def list_parts(path: str | Path) -> List[str]:
    validate_docx_path(path)
    with zipfile.ZipFile(path) as package:
        return package.namelist()


def read_parts(path: str | Path, part_names: Iterable[str]) -> Dict[str, bytes]:
    validate_docx_path(path)
    with zipfile.ZipFile(path) as package:
        return {name: package.read(name) for name in part_names if name in package.namelist()}


def assert_output_not_input(output_path: str | Path, inputs: Iterable[str | Path]) -> None:
    out = Path(output_path).resolve()
    for input_path in inputs:
        if out == Path(input_path).resolve():
            raise DocxError("Output path must not overwrite an input file.")


def validate_docx_can_open(path: str | Path) -> None:
    validate_docx_path(path)
    try:
        from docx import Document

        Document(str(path))
    except Exception as exc:  # pragma: no cover - exact parser failures vary
        raise DocxError(f"Generated docx cannot be opened by python-docx: {exc}") from exc
