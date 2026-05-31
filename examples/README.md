# Examples

This directory contains example configuration and can hold generated sample `.docx` files for local smoke testing.

The repository does not commit binary `.docx` example files yet. Generate them with:

```bash
python scripts/create_examples.py
```

This creates:

- `examples/template_basic.docx`
- `examples/content_basic.docx`

Then run the documented workflow:

```bash
python -m app.main inspect --template examples/template_basic.docx --content examples/content_basic.docx --out-dir workdir
python -m app.main format --template examples/template_basic.docx --content examples/content_basic.docx --mapping workdir/mapping.generated.json --out workdir/output.docx --report workdir/validation_report.html
```

`rules.example.yaml` shows the intended structure for rule overrides. In the current MVP, `style_map` is active. `page` and `formatting` are documented reserved fields for future expansion.

