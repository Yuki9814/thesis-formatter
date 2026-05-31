# Thesis Formatter / 论文格式助手

Thesis Formatter 是一个确定性 `.docx` 论文格式转移与校验工具。它的目标是把模板/样例 Word 文档中的格式规则尽量转移到待排版内容文档，并生成可检查的报告。

它不是“自动完美排版所有论文”的工具。当前版本是 MVP，适合做格式提取、段落角色识别、样式映射、基础格式应用和问题报告。真实论文的最终版式仍应在 Microsoft Word 中复核，后续阶段优先以 Windows Word 作为最终布局权威。

## Project Status

当前状态：MVP。

已支持：

- `.docx` 输入和输出。
- `inspect` 预检查流程：提取模板格式、分析内容结构、生成可编辑映射和 HTML 检查报告。
- `format` 格式化流程：读取映射文件，生成新的 `.docx` 和校验报告。
- 交付 readiness：在检查和格式化阶段给出“可交付 / 需复核 / 不建议交付”、评分、阻塞项、人工复核项和下一步动作。
- `doctor` 预检流程：检查依赖、输入 `.docx`、输出目录和 Word 复核环境。
- PySide6 GUI：文件选择、检查预演、映射编辑、执行格式化、报告查看。
- GUI 五步主流程：选择文件、模板体检、映射确认、生成文档、交付复核。
- 使用 `style_id` 执行样式应用，报告中展示 `style_name`。
- 读取/保留中文字体相关 `rFonts` 字段：`ascii`、`hAnsi`、`eastAsia`、`cs`。
- 保守清理段落级直接格式，默认保留字符级直接格式。
- 检测模板/样例质量，提示大量手动格式带来的风险。
- 检测 TOC、域、交叉引用、书签、公式、脚注/尾注等复杂 Word 特性，并在报告中提示复核。

暂不支持或不保证：

- 不处理 `.doc` 文件。
- 不保证完美分页。
- MVP 不自动更新目录、页码域、交叉引用或所有 Word 字段。
- MVP 不激进重建复杂分节、复杂页码体系或多节页眉页脚。
- 默认不使用 AI。
- 不保证“前人改好的论文”一定是可靠模板；若大量段落使用 `Normal` 加手动格式，自动转移可靠性会下降。
- MathType、异常嵌入对象、修订模式、复杂自定义域等需要人工复核。

Mac 当前是开发和包级验证环境，不是最终版式权威。最终布局复核应使用 Microsoft Word，后续阶段优先接入 Windows Word 自动化。

## Prerequisites

- Python 3.11+
- 推荐：`uv`
- 备选：`pip` + `venv`
- 可选 GUI 依赖：`PySide6`
- 未来可选 Windows 自动化依赖：Microsoft Word for Windows + `pywin32`，当前 MVP 未实现
- 输入格式：仅 `.docx`，不支持 `.doc`

## Installation

### uv

安装核心 CLI 依赖：

```bash
uv sync
```

安装 GUI 依赖：

```bash
uv sync --extra gui
```

安装开发/测试依赖：

```bash
uv sync --extra dev
```

### pip / venv

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

安装 GUI：

```bash
pip install -e ".[gui]"
```

安装测试依赖：

```bash
pip install -e ".[dev]"
```

## Quick Start

仓库不提交二进制示例 `.docx`。先生成最小示例文件：

```bash
python scripts/create_examples.py
```

这会创建：

- `examples/template_basic.docx`
- `examples/content_basic.docx`

Step 0：可选，运行本地预检。

```bash
python -m app.main doctor --template examples/template_basic.docx --content examples/content_basic.docx --out-dir workdir
```

Step 1：运行检查/预演。

```bash
python -m app.main inspect --template examples/template_basic.docx --content examples/content_basic.docx --out-dir workdir
```

Step 2：打开并确认/编辑映射。

```text
workdir/mapping.generated.json
```

Step 3：执行格式化。

```bash
python -m app.main format --template examples/template_basic.docx --content examples/content_basic.docx --mapping workdir/mapping.generated.json --out workdir/output.docx --report workdir/validation_report.html
```

Step 4：打开结果并复核。

- `workdir/output.docx`：用 Microsoft Word 打开，确认没有修复提示。
- `workdir/validation_report.html`：查看通过项、提示、警告和错误。
- `workdir/delivery_checklist.html`：按交付清单做 Word 内最终复核。

一条命令运行 smoke test：

```bash
python scripts/smoke_test.py
```

## CLI Reference

### inspect

```bash
python -m app.main inspect --template template.docx --content content.docx --out-dir workdir [--rules rules.yaml]
```

Options:

- `--template`：目标格式模板或已排版样例 `.docx`。
- `--content`：待排版内容 `.docx`。
- `--out-dir`：检查产物输出目录。
- `--rules`：可选规则文件。MVP 中仅 `style_map` 会覆盖自动样式映射。

`inspect` 当前没有 `--strict` 或 `--debug-dir`。

### doctor

```bash
python -m app.main doctor [--template template.docx] [--content content.docx] [--out-dir workdir] [--require-gui] [--json]
```

Options:

- `--template`：可选，检查模板或样例文件是否是有效 `.docx`。
- `--content`：可选，检查内容文件是否是有效 `.docx`。
- `--out-dir`：可选，检查输出目录或其父目录是否可写。
- `--require-gui`：把 PySide6 缺失视为错误；默认只作为提示。
- `--json`：输出机器可读 JSON。

Exit codes:

- `0`：没有 error。warning 仍会显示，但不阻塞。
- `2`：存在输入、依赖或输出目录错误。

### format

```bash
python -m app.main format --template template.docx --content content.docx --mapping mapping.json --out output.docx --report validation_report.html [--strict] [--debug-dir debug]
```

Options:

- `--template`：目标格式模板或已排版样例 `.docx`。
- `--content`：待排版内容 `.docx`。
- `--mapping`：人工确认后的映射 JSON，通常来自 `inspect` 生成的 `mapping.generated.json`。
- `--out`：新生成的输出 `.docx`。
- `--report`：HTML 校验报告路径。
- `--strict`：严格模式。缺失映射和低置信度映射都会阻塞格式化。
- `--debug-dir`：保留调试文件，例如中间 XML 和失败上下文。

`format` 当前不支持 `--rules`。需要先在 `inspect --rules` 阶段生成/调整映射，再传入 `--mapping`。

### gui

```bash
python -m app.main gui
```

GUI 需要安装 `PySide6`：

```bash
uv sync --extra gui
```

或：

```bash
pip install -e ".[gui]"
```

## Mapping File

`inspect` 会生成可编辑映射文件：

```text
workdir/mapping.generated.json
```

内部格式化尽量使用 `style_id`，因为 Word 样式名可能重复、翻译或显示不同。报告和 GUI 会展示 `style_name`，便于人工确认。

当前实际 schema 是 `entries` 数组，不是 `role_to_style` 对象。示例：

```json
{
  "generated_at": "2026-05-18T00:00:00+00:00",
  "entries": [
    {
      "role": "heading_1",
      "style_id": "Heading1",
      "style_name": "论文一级标题",
      "confidence": 0.92,
      "source": "generated",
      "required": true,
      "warning": null
    },
    {
      "role": "body",
      "style_id": "BodyText",
      "style_name": "正文",
      "confidence": 0.88,
      "source": "generated",
      "required": true,
      "warning": null
    }
  ],
  "low_confidence_threshold": 0.75,
  "notes": []
}
```

可编辑字段：

- `style_id`：优先编辑，格式化时实际使用。
- `style_name`：用于显示和报告，建议与 `style_id` 对应。
- `confidence`：可保留生成值；`--strict` 会用它判断是否阻塞。

不要删除 `role`、`required` 或 `low_confidence_threshold`，除非明确知道后果。

## rules.yaml

示例文件：

```text
examples/rules.example.yaml
```

MVP 当前实际使用：

- `style_map`：覆盖自动角色到样式的匹配。

示例：

```yaml
style_map:
  heading_1: "论文一级标题"
  heading_2: "论文二级标题"
  body: "正文"
  abstract: "摘要正文"
  keywords: "关键词"
  figure_caption: "图题"
  table_caption: "表题"
  reference_item: "参考文献正文"
```

`style_map` 的值可以是模板中的 `style_id` 或 `style_name`。匹配成功后会写入 `mapping.generated.json`。

`examples/rules.example.yaml` 也包含 `page` 和 `formatting` 示例字段：

```yaml
page:
  size: A4
  margin:
    top_cm: 2.5
    bottom_cm: 2.5
    left_cm: 3.0
    right_cm: 2.5

formatting:
  normalize_paragraph_direct_formatting: true
  preserve_character_direct_formatting: true
```

这些字段在 MVP 中是保留字段：当前页面设置仍来自 Word 模板/样例；当前直接格式策略固定为“可规范段落级直接格式，默认保留字符级直接格式”。

## Output Files

### inspect outputs

- `format_profile.json`：模板/样例格式档案，包括样式、页面设置、`rFonts`、模板质量、复杂特性检测。
- `content_structure.json`：内容文档段落结构，包括段落索引、文本预览、识别角色、当前样式、置信度。
- `mapping.generated.json`：可编辑的角色到目标样式映射。
- `readiness_result.json`：检查阶段交付风险结论，包括评分、阻塞项、人工复核项和下一步动作。
- `inspection_report.html`：检查报告，适合人工确认模板质量和映射结果。

### format outputs

- 输出 `.docx`：新的格式化文档。输入文件不会被覆盖。
- `validation_result.json`：机器可读校验结果。
- `validation_report.html`：人工可读校验报告。
- `delivery_checklist.json`：机器可读交付检查清单。
- `delivery_checklist.html`：人工可读交付检查清单，重点提示 Word 内复核项。

## Validation Report

报告顶部会先显示交付 readiness：

- `可交付`：没有阻塞项，仍建议保留报告并完成 Word 内目检。
- `需复核`：输出可继续处理，但存在低置信度映射、复杂字段、模板质量或直接格式等风险。
- `不建议交付`：存在 error 或缺失必需映射，需要修复后重跑。

报告严重级别：

- `pass`：整体或某项检查通过。当前 HTML 主要以无 issue 或 summary 表达通过状态。
- `info`：提示信息，通常不阻塞，例如保留的段落覆盖格式。
- `warning`：需要人工复核，例如低置信度映射、复杂 Word 字段、模板质量风险。
- `error`：可能的格式失败或缺失映射，需要修复后重跑。

警告不等于失败，但不能忽略。错误通常意味着输出不可信或某些角色没有正确应用样式。

## Strict Mode And Exit Codes

默认模式：

- 缺失 required 映射会阻塞格式化。
- 低置信度映射会进入报告，但不阻塞。
- 校验有 error 时，CLI 返回非 0。

`--strict`：

- 缺失 required 映射会阻塞格式化。
- 低置信度 required 映射也会阻塞格式化。

Exit codes:

- `0`：成功，且校验没有 error。
- `1`：校验失败或映射策略阻塞。
- `2`：无效输入或文件错误，例如不是 `.docx`、文件不存在、映射 JSON 无效。
- `3`：内部处理错误。

## Safety And Preservation Policy

- 输入文件永远不会被修改。
- 输出总是写到新的 `.docx` 路径。
- 格式化先写临时 `.docx`，确认可打开后再移动到最终输出路径。
- 内容文档作为基础包，尽量保留图片、表格、公式、脚注、尾注、书签、批注、字段和 relationships。
- 默认保留字符级直接格式，例如加粗、斜体、上下标、特殊内联格式。
- 段落级格式可能被规范化，例如对齐、缩进、段前段后、行距。

## Template / Reference Quality Guidance

推荐输入优先级：

1. Clean template document  
   最可靠。应包含可复用 Word 样式，例如“论文一级标题”“正文”“图题”“参考文献正文”。

2. Previously corrected reference thesis document  
   实用但风险更高。前人论文可能大量使用手动格式，样式名和真实用途不一定一致。必须认真检查 `inspection_report.html` 和 `mapping.generated.json`。

3. `rules.yaml`  
   用来覆盖自动映射。适合学校给了明确样式名，或自动匹配不准时使用。

如果大多数段落都是 `Normal` 样式，再叠加手动字体、字号、缩进和行距，自动格式转移会明显不可靠。MVP 会在模板质量检查中给出警告。

## Chinese Font Handling

中文字体不能只依赖 `python-docx` 的 `font.name`。Word XML 中字体通常分布在 `w:rFonts` 的多个字段：

- `ascii`
- `hAnsi`
- `eastAsia`
- `cs`

MVP 会读取/保留这些字段，并通过导入模板样式来应用中文字体。若 Word 中看到中文字体没有按预期生效，优先检查模板样式里的 `eastAsia` 是否正确。

## Limitations

- 不处理 `.doc`。
- 不保证完美分页。
- 不自动更新 TOC、页码字段、交叉引用或所有 Word 字段。
- 不激进重建复杂分节、页码体系、页眉页脚。
- 不默认使用 AI。
- 不保证前人改好的论文一定是可靠样式模板。
- MathType、异常嵌入对象、修订、复杂自定义字段可能需要人工复核。
- Mac 生成结果可以用于开发验证，但最终版式应在 Microsoft Word 中检查，后续阶段优先 Windows Word。

## Development

### Project structure

```text
app/                 CLI entrypoint and service orchestration
core/                deterministic .docx extraction, mapping, formatting, validation
gui/                 PySide6 GUI
models/              pydantic data models
examples/            example rules and generated sample .docx files
scripts/             example generation and smoke test helpers
tests/               pytest tests and generated fixtures
docs/architecture.md architecture notes
```

### Run tests

```bash
uv run --python 3.11 --extra dev pytest -q
```

or after `pip install -e ".[dev]"`:

```bash
pytest -q
```

### Run CLI locally

```bash
python scripts/create_examples.py
python -m app.main inspect --template examples/template_basic.docx --content examples/content_basic.docx --out-dir workdir
python -m app.main format --template examples/template_basic.docx --content examples/content_basic.docx --mapping workdir/mapping.generated.json --out workdir/output.docx --report workdir/validation_report.html
```

### Launch GUI

```bash
uv sync --extra gui
python -m app.main gui
```

### Lint / type checks

No lint or type-check tool is configured yet. Add `ruff`, `mypy`, or `pyright` before documenting those commands as required checks.

## Acceptance Checklist

- [ ] `inspect` command runs successfully.
- [ ] `mapping.generated.json` is produced and editable.
- [ ] `readiness_result.json` explains delivery risk and next actions.
- [ ] `format` command produces `output.docx`.
- [ ] `delivery_checklist.html` lists Word review items before final handoff.
- [ ] `output.docx` opens in Microsoft Word without a repair prompt.
- [ ] Page size and margins match the template.
- [ ] Heading/body/caption/reference styles are applied.
- [ ] Images and tables remain present.
- [ ] `validation_report.html` lists passes/warnings/errors clearly.

## Troubleshooting

### Input is not a `.docx`

Fix: save the file as `.docx` in Microsoft Word. `.doc` is not supported.

### Missing mapping

Fix: open `mapping.generated.json`, find the role with `style_id: null`, and set it to a valid template style ID. Re-run `format`.

### Low confidence mapping

Fix: inspect the role, `style_name`, and sample paragraphs. Edit the mapping if needed. Use `--strict` to block low-confidence mappings.

### Output document cannot be opened

Fix: rerun with `--debug-dir debug`, inspect preserved XML, and verify the input `.docx` opens normally in Word.

### Style name exists but `style_id` mismatch

Fix: prefer `style_id` from `format_profile.json`. Word display names can differ from internal IDs.

### Chinese font did not apply correctly

Fix: verify template style `rFonts.eastAsia`. Chinese fonts need `eastAsia`, not only `font.name`.

### TOC or page numbers did not update

Fix: open the output in Microsoft Word and update fields manually. MVP reports these fields but does not update them.

### GUI dependency missing

Fix:

```bash
uv sync --extra gui
```

or:

```bash
pip install -e ".[gui]"
```

## More Documentation

- [Architecture](docs/architecture.md)
- [Examples](examples/README.md)
