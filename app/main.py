from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.services import (
    doctor_check,
    format_documents,
    inspect_documents,
    public_error_message,
    validation_result_for_error,
    write_debug_error,
)
from core.docx_loader import DocxError
from core.formatter_engine import MappingConsistencyError, MappingPolicyError
from core.report_generator import write_delivery_checklist, write_validation_report
from models.io import model_to_json, write_model
from pydantic import ValidationError


EXIT_SUCCESS = 0
EXIT_VALIDATION_OR_MAPPING_FAILURE = 1
EXIT_INPUT_OR_FILE_ERROR = 2
EXIT_INTERNAL_ERROR = 3


def _is_input_error(exc: Exception) -> bool:
    return isinstance(exc, (DocxError, FileNotFoundError, json.JSONDecodeError, ValidationError))


def _inspect(args: argparse.Namespace) -> int:
    try:
        inspect_documents(args.template, args.content, args.out_dir, rules_path=args.rules)
    except Exception as exc:
        print(f"Inspection failed: {public_error_message(exc)}", file=sys.stderr)
        return EXIT_INPUT_OR_FILE_ERROR if _is_input_error(exc) else EXIT_INTERNAL_ERROR
    print(f"Inspection artifacts written to: {Path(args.out_dir).resolve()}")
    return EXIT_SUCCESS


def _format(args: argparse.Namespace) -> int:
    try:
        result = format_documents(
            template_path=args.template,
            content_path=args.content,
            mapping_path=args.mapping,
            output_path=args.out,
            report_path=args.report,
            strict=args.strict,
            debug_dir=args.debug_dir,
            force=args.force,
        )
    except Exception as exc:
        write_debug_error(args.debug_dir, exc)
        result = validation_result_for_error(args.out, exc)
        report = Path(args.report)
        report.parent.mkdir(parents=True, exist_ok=True)
        write_validation_report(report, result)
        write_model(report.parent / "validation_result.json", result)
        if result.readiness:
            write_model(report.parent / "delivery_checklist.json", result.readiness)
        write_delivery_checklist(report.parent / "delivery_checklist.html", result)
        print(f"Formatting failed: {public_error_message(exc)}", file=sys.stderr)
        print(f"Failure report written to: {Path(args.report).name}", file=sys.stderr)
        if isinstance(exc, (MappingPolicyError, MappingConsistencyError)):
            return EXIT_VALIDATION_OR_MAPPING_FAILURE
        if _is_input_error(exc):
            return EXIT_INPUT_OR_FILE_ERROR
        return EXIT_INTERNAL_ERROR
    print(f"Output written to: {Path(args.out).resolve()}")
    print(f"Validation report written to: {Path(args.report).resolve()}")
    print(f"Delivery checklist written to: {(Path(args.report).parent / 'delivery_checklist.html').resolve()}")
    return EXIT_SUCCESS if result.passed else EXIT_VALIDATION_OR_MAPPING_FAILURE


def _doctor(args: argparse.Namespace) -> int:
    result = doctor_check(args.template, args.content, args.out_dir, require_gui=args.require_gui)
    if args.json:
        print(model_to_json(result))
    else:
        print("Doctor summary:", result.summary)
        for check in result.checks:
            line = f"[{check.status}] {check.name}: {check.message}"
            print(line)
            if check.suggested_fix:
                print(f"  fix: {check.suggested_fix}")
    return EXIT_SUCCESS if result.passed else EXIT_INPUT_OR_FILE_ERROR


def _gui(_: argparse.Namespace) -> int:
    from gui.main_window import run_gui

    return run_gui()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="thesis-formatter")
    sub = parser.add_subparsers(dest="command")

    inspect_parser = sub.add_parser("inspect", help="Analyze template/content and generate editable mapping.")
    inspect_parser.add_argument("--template", required=True)
    inspect_parser.add_argument("--content", required=True)
    inspect_parser.add_argument("--out-dir", required=True)
    inspect_parser.add_argument("--rules")
    inspect_parser.set_defaults(func=_inspect)

    format_parser = sub.add_parser("format", help="Format content docx using an explicit mapping.")
    format_parser.add_argument("--template", required=True)
    format_parser.add_argument("--content", required=True)
    format_parser.add_argument("--mapping", required=True)
    format_parser.add_argument("--out", required=True)
    format_parser.add_argument("--report", required=True)
    format_parser.add_argument("--strict", action="store_true")
    format_parser.add_argument("--debug-dir")
    format_parser.add_argument("--force", action="store_true")
    format_parser.set_defaults(func=_format)

    doctor_parser = sub.add_parser("doctor", help="Preflight dependencies, inputs, and output location.")
    doctor_parser.add_argument("--template")
    doctor_parser.add_argument("--content")
    doctor_parser.add_argument("--out-dir")
    doctor_parser.add_argument("--require-gui", action="store_true")
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.set_defaults(func=_doctor)

    gui_parser = sub.add_parser("gui", help="Launch PySide6 GUI.")
    gui_parser.set_defaults(func=_gui)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        args = parser.parse_args(["gui"])
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
