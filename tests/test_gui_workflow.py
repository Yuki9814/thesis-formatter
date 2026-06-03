from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture()
def qapp():
    widgets = pytest.importorskip("PySide6.QtWidgets")
    app = widgets.QApplication.instance() or widgets.QApplication([])
    return app


@pytest.fixture()
def main_window(qapp):
    from gui.main_window import MainWindow

    window = MainWindow()
    yield window
    window.close()


def test_main_window_initial_state(main_window) -> None:
    assert main_window.tabs.count() == 5
    assert main_window.statusBar().currentMessage() == "就绪"
    assert main_window.output_edit.text().endswith("workdir/formatted.docx")


def test_required_paths_validate_inputs_for_inspect_and_format(main_window, simple_template: Path, simple_content: Path, tmp_path: Path) -> None:
    main_window.template_edit.setText(str(simple_template))
    main_window.content_edit.setText(str(simple_content))
    main_window.workdir_edit.setText(str(tmp_path / "workdir"))
    template, content, workdir, output = main_window._required_paths(require_output=False)
    assert template == simple_template
    assert content == simple_content
    assert workdir == tmp_path / "workdir"
    assert output is None

    main_window.output_edit.setText(str(simple_content))
    with pytest.raises(Exception, match="overwrite|覆盖|输入"):
        main_window._required_paths(require_output=True)


def test_preflight_renders_doctor_result(main_window, simple_template: Path, simple_content: Path, tmp_path: Path) -> None:
    main_window.template_edit.setText(str(simple_template))
    main_window.content_edit.setText(str(simple_content))
    main_window.workdir_edit.setText(str(tmp_path / "workdir"))
    main_window.run_preflight()
    assert "预检结果" in main_window.preflight_view.toPlainText()
    assert "dependency:lxml" in main_window.preflight_view.toPlainText()


def test_mapping_table_uses_candidate_combo(main_window, simple_template: Path, simple_content: Path, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QComboBox

    from app.services import inspect_documents
    from models import StyleMapping
    from models.io import load_model

    out_dir = tmp_path / "workdir"
    inspect_documents(simple_template, simple_content, out_dir)
    main_window.mapping_path = out_dir / "mapping.generated.json"
    main_window.load_mapping_table(main_window.mapping_path)

    combo = main_window.mapping_table.cellWidget(0, 1)
    assert isinstance(combo, QComboBox)
    assert main_window.mapping_table.horizontalHeaderItem(0).text() == "角色"

    mapping = main_window.mapping_from_table()
    source = load_model(main_window.mapping_path, StyleMapping)
    assert {entry.role for entry in mapping.entries} == {entry.role for entry in source.entries}
    assert all(entry.required == source.by_role()[entry.role].required for entry in mapping.entries)


def test_format_failure_generates_sanitized_report(main_window, simple_content: Path, tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)
    output = tmp_path / "output.docx"
    report = tmp_path / "workdir" / "validation_report.html"
    debug = tmp_path / "workdir" / "debug"

    exc = ValueError(f"raw failure at {tmp_path}")
    main_window._format_failed(exc, output, report, debug)

    report_text = report.read_text(encoding="utf-8")
    assert "format.failed" in report_text
    assert str(tmp_path) not in report_text
    assert (debug / "failure.txt").exists()
    assert main_window.tabs.currentIndex() == 4
