from __future__ import annotations

import html
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
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

from app.services import (
    doctor_check,
    format_documents,
    inspect_documents,
    public_error_message,
    validation_result_for_error,
    write_debug_error,
)
from core.docx_loader import assert_safe_output_path, validate_docx_path
from core.report_generator import write_delivery_checklist, write_validation_report
from gui.file_drop_widget import FileDropLineEdit
from models import DoctorResult, ReadinessResult, StyleMapping, ValidationResult
from models.io import load_model, model_to_json, write_model


ROLE_LABELS = {
    "abstract": "摘要",
    "appendix": "附录",
    "body": "正文",
    "equation": "公式",
    "figure_caption": "图题",
    "heading_1": "一级标题",
    "heading_2": "二级标题",
    "heading_3": "三级标题",
    "keywords": "关键词",
    "reference_heading": "参考文献标题",
    "reference_item": "参考文献条目",
    "table_caption": "表题",
    "toc": "目录",
}


class TaskWorker(QObject):
    finished = Signal(object)
    failed = Signal(object)

    def __init__(self, task: Callable[[], object]) -> None:
        super().__init__()
        self.task = task

    def run(self) -> None:
        try:
            self.finished.emit(self.task())
        except Exception as exc:  # pragma: no cover - exercised through GUI integration tests
            self.failed.emit(exc)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("论文格式助手")
        self.resize(1120, 760)
        self.mapping_path: Path | None = None
        self.current_mapping: StyleMapping | None = None
        self._output_was_auto = True
        self._active_thread: QThread | None = None
        self._active_worker: TaskWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.addTab(self._files_tab(), "1 选择文件")
        self.tabs.addTab(self._inspect_tab(), "2 模板体检")
        self.tabs.addTab(self._mapping_tab(), "3 映射确认")
        self.tabs.addTab(self._run_tab(), "4 生成文档")
        self.tabs.addTab(self._report_tab(), "5 交付复核")
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
        self.output_edit = QLineEdit(str(Path.cwd() / "workdir" / "formatted.docx"))
        self.output_edit.textEdited.connect(self._mark_output_manual)
        rows = [
            self._path_row("模板/样例 .docx", self.template_edit, "选择", self.choose_template),
            self._path_row("内容 .docx", self.content_edit, "选择", self.choose_content),
            self._path_row("工作目录", self.workdir_edit, "选择", self.choose_workdir),
            self._path_row("输出 .docx", self.output_edit, "选择", self.choose_output),
        ]
        for row, widgets in enumerate(rows):
            for col, widget in enumerate(widgets):
                layout.addWidget(widget, row, col)
        self.preflight_btn = QPushButton("运行预检")
        self.preflight_btn.clicked.connect(self.run_preflight)
        self.run_inspect_btn = QPushButton("运行模板体检")
        self.run_inspect_btn.clicked.connect(self.run_inspect)
        layout.addWidget(self.preflight_btn, len(rows), 1)
        layout.addWidget(self.run_inspect_btn, len(rows), 2)
        self.preflight_view = QTextBrowser()
        layout.addWidget(self.preflight_view, len(rows) + 1, 0, 1, 3)
        return page

    def _inspect_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.inspect_summary = QTextBrowser()
        self.inspect_summary.setMaximumHeight(180)
        self.inspect_view = QTextBrowser()
        layout.addWidget(self.inspect_summary)
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
        self.mapping_table = QTableWidget(0, 9)
        self.mapping_table.setHorizontalHeaderLabels(
            [
                "角色",
                "目标样式",
                "样式名称",
                "置信度",
                "必填",
                "判断依据",
                "内容样本",
                "目标样式样本",
                "候选样式",
            ]
        )
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
        self.run_format_btn = QPushButton("生成格式化文档")
        self.run_format_btn.clicked.connect(self.run_format)
        layout.addWidget(options)
        layout.addWidget(self.run_format_btn)
        layout.addWidget(self.run_log)
        return page

    def _report_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        buttons = QHBoxLayout()
        open_output = QPushButton("打开输出 Word")
        open_workdir = QPushButton("打开工作目录")
        open_debug = QPushButton("打开调试目录")
        open_checklist = QPushButton("打开交付清单")
        open_output.clicked.connect(self.open_output)
        open_workdir.clicked.connect(self.open_workdir)
        open_debug.clicked.connect(self.open_debug_dir)
        open_checklist.clicked.connect(self.open_delivery_checklist)
        buttons.addWidget(open_output)
        buttons.addWidget(open_checklist)
        buttons.addWidget(open_workdir)
        buttons.addWidget(open_debug)
        buttons.addStretch()
        self.report_summary = QTextBrowser()
        self.report_summary.setMaximumHeight(180)
        self.report_view = QTextBrowser()
        layout.addLayout(buttons)
        layout.addWidget(self.report_summary)
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
            if self._output_was_auto:
                self.output_edit.setText(str(Path(path).expanduser() / "formatted.docx"))

    def choose_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "选择输出文件", "", "Word Document (*.docx)")
        if path:
            self._output_was_auto = False
            self.output_edit.setText(path)

    def _mark_output_manual(self) -> None:
        self._output_was_auto = False

    def _required_paths(self, require_output: bool = True) -> tuple[Path, Path, Path, Path | None]:
        required = [self.template_edit.text().strip(), self.content_edit.text().strip(), self.workdir_edit.text().strip()]
        if require_output:
            required.append(self.output_edit.text().strip())
        if not all(required):
            raise ValueError("请先填写模板、内容、工作目录和输出路径。" if require_output else "请先填写模板、内容和工作目录。")
        template = Path(self.template_edit.text()).expanduser()
        content = Path(self.content_edit.text()).expanduser()
        workdir = Path(self.workdir_edit.text()).expanduser()
        output = Path(self.output_edit.text()).expanduser() if require_output else None
        validate_docx_path(template)
        validate_docx_path(content)
        target = workdir if workdir.exists() else workdir.parent
        if not target.exists():
            raise ValueError("工作目录的上级目录不存在。")
        if not target.is_dir():
            raise ValueError("工作目录必须位于普通目录中。")
        if require_output and output is not None:
            assert_safe_output_path(output, [template, content], force=False)
        return template, content, workdir, output

    def _set_busy(self, busy: bool, message: str = "就绪") -> None:
        for button in (self.preflight_btn, self.run_inspect_btn, self.run_format_btn):
            button.setEnabled(not busy)
        self.statusBar().showMessage(message)

    def _start_task(self, task: Callable[[], object], on_finished: Callable[[object], None], on_failed: Callable[[Exception], None]) -> None:
        self._set_busy(True, "处理中...")
        thread = QThread(self)
        worker = TaskWorker(task)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(on_finished)
        worker.failed.connect(on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._set_busy(False))
        self._active_thread = thread
        self._active_worker = worker
        thread.start()

    def _readiness_html(self, readiness: ReadinessResult | None) -> str:
        if readiness is None:
            return "<p>暂无交付结论。</p>"
        blocking = "".join(f"<li>{html.escape(item)}</li>" for item in readiness.blocking_items) or "<li>没有阻塞项。</li>"
        reviews = "".join(f"<li>{html.escape(item)}</li>" for item in readiness.manual_review_items) or "<li>没有额外人工复核项。</li>"
        actions = "".join(f"<li>{html.escape(item)}</li>" for item in readiness.next_actions) or "<li>保留报告并完成最终复核。</li>"
        return f"""
        <h2>{html.escape(readiness.status)} · {readiness.score}/100</h2>
        <p>风险等级：{html.escape(readiness.risk_level)}</p>
        <h3>阻塞项</h3><ul>{blocking}</ul>
        <h3>人工复核项</h3><ul>{reviews}</ul>
        <h3>下一步</h3><ul>{actions}</ul>
        """

    def _doctor_html(self, result: DoctorResult) -> str:
        rows = []
        for check in result.checks:
            rows.append(
                "<tr>"
                f"<td>{html.escape(check.status)}</td><td>{html.escape(check.name)}</td>"
                f"<td>{html.escape(check.message)}</td><td>{html.escape(check.suggested_fix or '')}</td>"
                "</tr>"
            )
        return f"""
        <h2>预检结果：{'通过' if result.passed else '需要处理'}</h2>
        <p>pass: {result.summary.get('pass', 0)} · warning: {result.summary.get('warning', 0)} · error: {result.summary.get('error', 0)}</p>
        <table border="1" cellspacing="0" cellpadding="6">
          <tr><th>状态</th><th>项目</th><th>说明</th><th>建议</th></tr>
          {''.join(rows)}
        </table>
        """

    def run_preflight(self) -> None:
        try:
            template, content, workdir, _ = self._required_paths(require_output=False)
            result = doctor_check(template, content, workdir, require_gui=True)
            self.preflight_view.setHtml(self._doctor_html(result))
            self.statusBar().showMessage("预检完成")
        except Exception as exc:
            self.show_error(exc)

    def run_inspect(self) -> None:
        try:
            template, content, workdir, _ = self._required_paths(require_output=False)
            self._start_task(
                lambda: inspect_documents(template, content, workdir),
                lambda _: self._inspect_finished(workdir),
                self._task_failed,
            )
        except Exception as exc:
            self.show_error(exc)

    def _inspect_finished(self, workdir: Path) -> None:
        self.mapping_path = workdir / "mapping.generated.json"
        self.load_mapping_table(self.mapping_path)
        readiness = load_model(workdir / "readiness_result.json", ReadinessResult)
        self.inspect_summary.setHtml(self._readiness_html(readiness))
        self.inspect_view.setSource((workdir / "inspection_report.html").as_uri())
        self.tabs.setCurrentIndex(1)
        self.statusBar().showMessage("检查完成")

    def _task_failed(self, exc: Exception) -> None:
        self.show_error(exc)

    def load_mapping_table(self, path: Path) -> None:
        mapping = load_model(path, StyleMapping)
        self.current_mapping = mapping
        entries = sorted(
            mapping.entries,
            key=lambda entry: (
                not (entry.required and (not entry.style_id or entry.confidence < mapping.low_confidence_threshold)),
                not entry.required,
                entry.role,
            ),
        )
        self.mapping_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            candidates = "\n".join(
                f"{item.style_name} ({item.style_id}, {item.score:.2f})" for item in entry.candidate_styles[:3]
            )
            values = [
                ROLE_LABELS.get(entry.role, entry.role),
                entry.style_id or "",
                entry.style_name or "",
                f"{entry.confidence:.2f}",
                "是" if entry.required else "否",
                entry.confidence_reason or entry.warning or "",
                "\n".join(entry.sample_texts),
                "\n".join(entry.target_style_samples),
                candidates,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if col == 0:
                    item.setData(Qt.UserRole, entry.role)
                if entry.required and entry.confidence < mapping.low_confidence_threshold:
                    item.setBackground(QColor("#fff7ed"))
                self.mapping_table.setItem(row, col, item)
            combo = QComboBox()
            seen: set[str] = set()
            options = []
            if entry.style_id:
                options.append((entry.style_name or entry.style_id, entry.style_id, entry.style_name or entry.style_id))
                seen.add(entry.style_id)
            for candidate in entry.candidate_styles:
                if candidate.style_id not in seen:
                    options.append(
                        (
                            f"{candidate.style_name} ({candidate.style_id}, {candidate.score:.2f})",
                            candidate.style_id,
                            candidate.style_name,
                        )
                    )
                    seen.add(candidate.style_id)
            if not options:
                options.append(("未选择", "", ""))
            for label, style_id, style_name in options:
                combo.addItem(label, (style_id, style_name))
            combo.currentIndexChanged.connect(lambda _, r=row: self._sync_style_from_combo(r))
            self.mapping_table.setCellWidget(row, 1, combo)
            self._sync_style_from_combo(row)
        self.mapping_table.resizeColumnsToContents()

    def _sync_style_from_combo(self, row: int) -> None:
        combo = self.mapping_table.cellWidget(row, 1)
        if not isinstance(combo, QComboBox):
            return
        style_id, style_name = combo.currentData()
        self.mapping_table.item(row, 1).setText(style_id)
        self.mapping_table.item(row, 2).setText(style_name)

    def mapping_from_table(self) -> StyleMapping:
        source = self.mapping_path or Path(self.workdir_edit.text()).expanduser() / "mapping.generated.json"
        mapping = load_model(source, StyleMapping)
        entries = {entry.role: entry for entry in mapping.entries}
        for row in range(self.mapping_table.rowCount()):
            role_item = self.mapping_table.item(row, 0)
            role = role_item.data(Qt.UserRole) if role_item is not None else None
            entry = entries.get(role)
            if entry is None:
                continue
            combo = self.mapping_table.cellWidget(row, 1)
            if isinstance(combo, QComboBox):
                style_id, style_name = combo.currentData()
                entry.style_id = style_id or None
                entry.style_name = style_name or None
            else:
                entry.style_id = self.mapping_table.item(row, 1).text().strip() or None
                entry.style_name = self.mapping_table.item(row, 2).text().strip() or None
        mapping.entries = list(entries.values())
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
            if output is None:
                raise ValueError("请先填写输出路径。")
            workdir.mkdir(parents=True, exist_ok=True)
            mapping = self.mapping_from_table()
            mapping_path = workdir / "mapping.gui.json"
            write_model(mapping_path, mapping)
            report_path = workdir / "validation_report.html"
            debug_dir = workdir / "debug" if self.debug_check.isChecked() else None
            strict = self.strict_check.isChecked()
            self.run_log.append("开始格式化...")
            self._start_task(
                lambda: self._format_task(template, content, mapping_path, output, report_path, debug_dir, strict),
                lambda result: self._format_finished(result, report_path),
                lambda exc: self._format_failed(exc, output, report_path, debug_dir),
            )
        except Exception as exc:
            self.run_log.append(f"失败: {public_error_message(exc)}")
            self.show_error(exc)

    def _format_task(
        self,
        template: Path,
        content: Path,
        mapping_path: Path,
        output: Path,
        report_path: Path,
        debug_dir: Path | None,
        strict: bool,
    ) -> ValidationResult:
        return format_documents(
            template,
            content,
            mapping_path,
            output,
            report_path,
            strict=strict,
            debug_dir=debug_dir,
            force=False,
        )

    def _format_finished(self, result: object, report_path: Path) -> None:
        if not isinstance(result, ValidationResult):
            raise ValueError("格式化结果无效。")
        self.run_log.append(model_to_json(result))
        if result.readiness:
            self.report_summary.setHtml(self._readiness_html(result.readiness))
        self.report_view.setSource(report_path.as_uri())
        self.tabs.setCurrentIndex(4)
        self.statusBar().showMessage("格式化完成")

    def _format_failed(self, exc: Exception, output: Path, report_path: Path, debug_dir: Path | None) -> None:
        write_debug_error(debug_dir, exc)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        result = validation_result_for_error(output, exc)
        write_validation_report(report_path, result)
        write_model(report_path.parent / "validation_result.json", result)
        if result.readiness:
            write_model(report_path.parent / "delivery_checklist.json", result.readiness)
            self.report_summary.setHtml(self._readiness_html(result.readiness))
        write_delivery_checklist(report_path.parent / "delivery_checklist.html", result)
        self.run_log.append(f"失败: {public_error_message(exc)}")
        self.report_view.setSource(report_path.as_uri())
        self.tabs.setCurrentIndex(4)
        self.show_error(exc)

    def show_error(self, exc: Exception) -> None:
        QMessageBox.critical(self, "错误", public_error_message(exc))
        self.statusBar().showMessage("发生错误")

    def _open_path(self, path: Path) -> None:
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            QMessageBox.information(self, "尚未生成", f"路径不存在：{path.name}")

    def open_output(self) -> None:
        self._open_path(Path(self.output_edit.text()).expanduser())

    def open_workdir(self) -> None:
        self._open_path(Path(self.workdir_edit.text()).expanduser())

    def open_debug_dir(self) -> None:
        self._open_path(Path(self.workdir_edit.text()).expanduser() / "debug")

    def open_delivery_checklist(self) -> None:
        self._open_path(Path(self.workdir_edit.text()).expanduser() / "delivery_checklist.html")


def run_gui() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
