from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services import format_documents, inspect_documents, validation_result_for_error
from core.report_generator import write_validation_report
from gui.file_drop_widget import FileDropLineEdit
from models import StyleMapping
from models.io import load_model, model_to_json, write_model


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("论文格式助手")
        self.resize(1120, 760)
        self.mapping_path: Path | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.addTab(self._files_tab(), "文件")
        self.tabs.addTab(self._inspect_tab(), "检查")
        self.tabs.addTab(self._mapping_tab(), "映射")
        self.tabs.addTab(self._run_tab(), "执行")
        self.tabs.addTab(self._report_tab(), "报告")
        self.statusBar().showMessage("就绪")

        open_workdir = QAction("打开工作目录", self)
        open_workdir.triggered.connect(self.open_workdir)
        self.menuBar().addAction(open_workdir)

    def _path_row(self, label: str, line: QLineEdit, button_text: str, slot) -> tuple[QLabel, QLineEdit, QPushButton]:
        button = QPushButton(button_text)
        button.clicked.connect(slot)
        return QLabel(label), line, button

    def _files_tab(self) -> QWidget:
        page = QWidget()
        layout = QGridLayout(page)
        self.template_edit = FileDropLineEdit()
        self.content_edit = FileDropLineEdit()
        self.workdir_edit = QLineEdit(str(Path.cwd() / "workdir"))
        self.output_edit = QLineEdit(str(Path.cwd() / "output" / "formatted.docx"))
        rows = [
            self._path_row("模板/样例 .docx", self.template_edit, "选择", self.choose_template),
            self._path_row("内容 .docx", self.content_edit, "选择", self.choose_content),
            self._path_row("工作目录", self.workdir_edit, "选择", self.choose_workdir),
            self._path_row("输出 .docx", self.output_edit, "选择", self.choose_output),
        ]
        for row, widgets in enumerate(rows):
            for col, widget in enumerate(widgets):
                layout.addWidget(widget, row, col)
        run_inspect = QPushButton("运行检查预演")
        run_inspect.clicked.connect(self.run_inspect)
        layout.addWidget(run_inspect, len(rows), 2)
        return page

    def _inspect_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.inspect_view = QTextBrowser()
        layout.addWidget(self.inspect_view)
        return page

    def _mapping_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        buttons = QHBoxLayout()
        import_btn = QPushButton("导入 mapping.json")
        export_btn = QPushButton("导出 mapping.json")
        import_btn.clicked.connect(self.import_mapping)
        export_btn.clicked.connect(self.export_mapping)
        buttons.addWidget(import_btn)
        buttons.addWidget(export_btn)
        buttons.addStretch()
        self.mapping_table = QTableWidget(0, 6)
        self.mapping_table.setHorizontalHeaderLabels(["role", "style_id", "style_name", "confidence", "required", "warning"])
        layout.addLayout(buttons)
        layout.addWidget(self.mapping_table)
        return page

    def _run_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        options = QGroupBox("执行选项")
        option_layout = QVBoxLayout(options)
        self.strict_check = QCheckBox("严格模式：低置信度映射也阻塞")
        self.debug_check = QCheckBox("保留调试文件")
        option_layout.addWidget(self.strict_check)
        option_layout.addWidget(self.debug_check)
        self.run_log = QTextEdit()
        self.run_log.setReadOnly(True)
        run_btn = QPushButton("执行格式化")
        run_btn.clicked.connect(self.run_format)
        layout.addWidget(options)
        layout.addWidget(run_btn)
        layout.addWidget(self.run_log)
        return page

    def _report_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        buttons = QHBoxLayout()
        open_output = QPushButton("打开输出 Word")
        open_workdir = QPushButton("打开工作目录")
        open_debug = QPushButton("打开调试目录")
        open_output.clicked.connect(self.open_output)
        open_workdir.clicked.connect(self.open_workdir)
        open_debug.clicked.connect(self.open_debug_dir)
        buttons.addWidget(open_output)
        buttons.addWidget(open_workdir)
        buttons.addWidget(open_debug)
        buttons.addStretch()
        self.report_view = QTextBrowser()
        layout.addLayout(buttons)
        layout.addWidget(self.report_view)
        return page

    def choose_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择模板/样例", "", "Word Document (*.docx)")
        if path:
            self.template_edit.setText(path)

    def choose_content(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择内容文档", "", "Word Document (*.docx)")
        if path:
            self.content_edit.setText(path)

    def choose_workdir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择工作目录")
        if path:
            self.workdir_edit.setText(path)

    def choose_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "选择输出文件", "", "Word Document (*.docx)")
        if path:
            self.output_edit.setText(path)

    def _required_paths(self) -> tuple[Path, Path, Path, Path]:
        if not all(
            [
                self.template_edit.text().strip(),
                self.content_edit.text().strip(),
                self.workdir_edit.text().strip(),
                self.output_edit.text().strip(),
            ]
        ):
            raise ValueError("请先填写模板、内容、工作目录和输出路径。")
        template = Path(self.template_edit.text()).expanduser()
        content = Path(self.content_edit.text()).expanduser()
        workdir = Path(self.workdir_edit.text()).expanduser()
        output = Path(self.output_edit.text()).expanduser()
        return template, content, workdir, output

    def run_inspect(self) -> None:
        try:
            template, content, workdir, _ = self._required_paths()
            self.statusBar().showMessage("正在检查...")
            inspect_documents(template, content, workdir)
            self.mapping_path = workdir / "mapping.generated.json"
            self.load_mapping_table(self.mapping_path)
            self.inspect_view.setSource((workdir / "inspection_report.html").as_uri())
            self.tabs.setCurrentIndex(1)
            self.statusBar().showMessage("检查完成")
        except Exception as exc:
            self.show_error(exc)

    def load_mapping_table(self, path: Path) -> None:
        mapping = load_model(path, StyleMapping)
        self.mapping_table.setRowCount(len(mapping.entries))
        for row, entry in enumerate(mapping.entries):
            values = [
                entry.role,
                entry.style_id or "",
                entry.style_name or "",
                f"{entry.confidence:.2f}",
                "true" if entry.required else "false",
                entry.warning or "",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col in {0, 3, 4, 5}:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.mapping_table.setItem(row, col, item)

    def mapping_from_table(self) -> StyleMapping:
        source = self.mapping_path or Path(self.workdir_edit.text()).expanduser() / "mapping.generated.json"
        mapping = load_model(source, StyleMapping)
        entries = mapping.entries
        for row, entry in enumerate(entries):
            entry.style_id = self.mapping_table.item(row, 1).text().strip() or None
            entry.style_name = self.mapping_table.item(row, 2).text().strip() or None
        mapping.entries = entries
        return mapping

    def import_mapping(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入 mapping.json", "", "JSON (*.json)")
        if path:
            self.mapping_path = Path(path)
            self.load_mapping_table(self.mapping_path)

    def export_mapping(self) -> None:
        try:
            path, _ = QFileDialog.getSaveFileName(self, "导出 mapping.json", "", "JSON (*.json)")
            if not path:
                return
            mapping = self.mapping_from_table()
            write_model(path, mapping)
            self.mapping_path = Path(path)
            self.statusBar().showMessage(f"映射已导出: {path}")
        except Exception as exc:
            self.show_error(exc)

    def run_format(self) -> None:
        try:
            template, content, workdir, output = self._required_paths()
            workdir.mkdir(parents=True, exist_ok=True)
            mapping = self.mapping_from_table()
            mapping_path = workdir / "mapping.gui.json"
            write_model(mapping_path, mapping)
            report_path = workdir / "validation_report.html"
            debug_dir = workdir / "debug" if self.debug_check.isChecked() else None
            self.run_log.append("开始格式化...")
            try:
                result = format_documents(
                    template,
                    content,
                    mapping_path,
                    output,
                    report_path,
                    strict=self.strict_check.isChecked(),
                    debug_dir=debug_dir,
                )
            except Exception as exc:
                result = validation_result_for_error(output, exc)
                write_validation_report(report_path, result)
                write_model(report_path.parent / "validation_result.json", result)
                raise
            self.run_log.append(model_to_json(result))
            self.report_view.setSource(report_path.as_uri())
            self.tabs.setCurrentIndex(4)
            self.statusBar().showMessage("格式化完成")
        except Exception as exc:
            self.run_log.append(f"失败: {type(exc).__name__}: {exc}")
            self.show_error(exc)

    def show_error(self, exc: Exception) -> None:
        QMessageBox.critical(self, "错误", f"{type(exc).__name__}: {exc}")
        self.statusBar().showMessage("发生错误")

    def _open_path(self, path: Path) -> None:
        if path.exists():
            subprocess.run(["open", str(path)], check=False)

    def open_output(self) -> None:
        self._open_path(Path(self.output_edit.text()).expanduser())

    def open_workdir(self) -> None:
        self._open_path(Path(self.workdir_edit.text()).expanduser())

    def open_debug_dir(self) -> None:
        self._open_path(Path(self.workdir_edit.text()).expanduser() / "debug")


def run_gui() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
