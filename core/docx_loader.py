from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from posixpath import normpath
from typing import Dict, Iterable, List
from zipfile import LargeZipFile


class DocxError(ValueError):
    pass


REQUIRED_PARTS = {"[Content_Types].xml", "word/document.xml"}
ZIP64_LIMIT = (1 << 32) - 1


@dataclass(frozen=True)
class DocxPackagePolicy:
    max_file_bytes: int = 100 * 1024 * 1024
    max_parts: int = 2_000
    max_part_uncompressed_bytes: int = 50 * 1024 * 1024
    max_total_uncompressed_bytes: int = 250 * 1024 * 1024
    max_compression_ratio: float = 100.0
    compression_ratio_min_bytes: int = 1 * 1024 * 1024


DEFAULT_PACKAGE_POLICY = DocxPackagePolicy()


def _is_unsafe_zip_name(name: str) -> bool:
    if not name or name.startswith(("/", "\\")):
        return True
    normalized = normpath(name.replace("\\", "/"))
    if normalized in {".", ".."}:
        return True
    return normalized.startswith("../") or "/../" in normalized


def validate_docx_package(path: str | Path, policy: DocxPackagePolicy = DEFAULT_PACKAGE_POLICY) -> Path:
    docx_path = Path(path).expanduser()
    if not docx_path.exists():
        raise DocxError("输入文件不存在。")
    if docx_path.suffix.lower() != ".docx":
        raise DocxError("仅支持 .docx 文件。")
    if docx_path.stat().st_size > policy.max_file_bytes:
        raise DocxError("输入 .docx 文件过大。")
    if not zipfile.is_zipfile(docx_path):
        raise DocxError("输入文件不是有效的 .docx zip 包。")

    try:
        with zipfile.ZipFile(docx_path) as package:
            infos = package.infolist()
    except LargeZipFile as exc:
        raise DocxError("输入 .docx 使用了不受支持的 ZIP64 结构。") from exc
    except zipfile.BadZipFile as exc:
        raise DocxError("输入文件不是有效的 .docx zip 包。") from exc

    if len(infos) > policy.max_parts:
        raise DocxError("输入 .docx 包含过多内部文件。")

    seen: set[str] = set()
    names: set[str] = set()
    total_uncompressed = 0
    for item in infos:
        if item.filename in seen:
            raise DocxError("输入 .docx 包含重复的内部文件名。")
        seen.add(item.filename)
        names.add(item.filename)
        if item.flag_bits & 0x1:
            raise DocxError("输入 .docx 包含加密的内部文件。")
        if _is_unsafe_zip_name(item.filename):
            raise DocxError("输入 .docx 包含不安全的内部文件路径。")
        if item.file_size > ZIP64_LIMIT or item.compress_size > ZIP64_LIMIT:
            raise DocxError("输入 .docx 使用了不受支持的 ZIP64 结构。")
        if item.file_size > policy.max_part_uncompressed_bytes:
            raise DocxError("输入 .docx 包含过大的内部文件。")
        total_uncompressed += item.file_size
        if total_uncompressed > policy.max_total_uncompressed_bytes:
            raise DocxError("输入 .docx 解压后体积过大。")
        if item.compress_size > 0 and item.file_size >= policy.compression_ratio_min_bytes:
            ratio = item.file_size / item.compress_size
            if ratio > policy.max_compression_ratio:
                raise DocxError("输入 .docx 压缩比异常，可能存在资源耗尽风险。")

    missing = REQUIRED_PARTS - names
    if missing:
        raise DocxError("输入 .docx 缺少必要的 Word 文档结构。")
    return docx_path


def validate_docx_path(path: str | Path) -> Path:
    return validate_docx_package(path)


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


def assert_safe_output_path(output_path: str | Path, inputs: Iterable[str | Path], force: bool = False) -> Path:
    output = Path(output_path).expanduser()
    if output.suffix.lower() != ".docx":
        raise DocxError("输出路径必须是 .docx 文件。")
    assert_output_not_input(output, inputs)
    if output.exists():
        if output.is_symlink():
            raise DocxError("输出路径不能是符号链接。")
        if not output.is_file():
            raise DocxError("输出路径必须是普通文件。")
        if not force:
            raise DocxError("输出文件已存在；如需覆盖，请显式使用 --force。")
    parent = output.parent
    if parent.exists() and parent.is_symlink():
        raise DocxError("输出目录不能是符号链接。")
    return output


def validate_docx_can_open(path: str | Path) -> None:
    validate_docx_path(path)
    try:
        from docx import Document

        Document(str(path))
    except Exception as exc:  # pragma: no cover - exact parser failures vary
        raise DocxError(f"Generated docx cannot be opened by python-docx: {exc}") from exc
