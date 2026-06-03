from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path

try:
    from scripts.create_examples import generate_examples
except ModuleNotFoundError:  # pragma: no cover - supports python scripts/smoke_test.py
    from create_examples import generate_examples


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str]) -> None:
    print("+", " ".join(command))
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(REPO_ROOT) if not existing else f"{REPO_ROOT}{os.pathsep}{existing}"
    subprocess.run(command, check=True, env=env)


def main() -> int:
    generate_examples("examples")
    workdir = Path("workdir")
    workdir.mkdir(exist_ok=True)
    _run(
        [
            sys.executable,
            "-m",
            "app.main",
            "inspect",
            "--template",
            "examples/template_basic.docx",
            "--content",
            "examples/content_basic.docx",
            "--out-dir",
            "workdir",
        ]
    )
    _run(
        [
            sys.executable,
            "-m",
            "app.main",
            "format",
            "--template",
            "examples/template_basic.docx",
            "--content",
            "examples/content_basic.docx",
            "--mapping",
            "workdir/mapping.generated.json",
            "--out",
            "workdir/output.docx",
            "--report",
            "workdir/validation_report.html",
            "--force",
        ]
    )
    print("Smoke test completed. Review workdir/output.docx and workdir/validation_report.html.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
