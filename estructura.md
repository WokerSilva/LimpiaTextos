## Estructura de carpetas (robusta y escalable)

```
limpiatextos/
├── input_pdfs/
│   └── SMNYL_Guia.pdf
├── workspace/
│   ├── <doc_id>/
│   │   ├── manifest.json
│   │   ├── plan.json
│   │   ├── normalized.pdf
│   │   ├── raw_text_pages.jsonl
│   │   ├── clean_text.txt
│   │   ├── clean_text_pages.jsonl
│   │   ├── sections.json
│   │   ├── tables/
│   │   ├── tables_index.json
│   │   ├── figures/
│   │   └── figures_index.json
│   └── sha256:b6f996ae4dfd8009c904db33c35c1a17c7a81062987b802adf934201393e3b44/
│       ├── clean_text.txt
│       ├── clean_text_pages.jsonl
│       ├── figures/
│       ├── manifest.json
│       ├── raw_text_pages.jsonl
│       ├── report.json
│       ├── sections.json
│       └── tables/
├── outputs/
│   ├── text/
│   │   └── sha256:b6f996ae4dfd8009c904db33c35c1a17c7a81062987b802adf934201393e3b44.txt
│   ├── md/
│   │   └── sha256:b6f996ae4dfd8009c904db33c35c1a17c7a81062987b802adf934201393e3b44.md
│   ├── jsonl/
│   │   └── sha256:b6f996ae4dfd8009c904db33c35c1a17c7a81062987b802adf934201393e3b44.jsonl
│   └── reports/
│       ├── summary.csv
│       └── sha256:b6f996ae4dfd8009c904db33c35c1a17c7a81062987b802adf934201393e3b44.json
├── src/
│   ├── limpiatextos/
│   │   ├── __init__.py
│   │   ├── cli.py
│   │   ├── config/
│   │   ├── core/
│   │   │   ├── models.py
│   │   │   ├── errors.py
│   │   │   ├── logging.py
│   │   │   └── qa.py
│   │   ├── pipeline/
│   │   │   ├── runner.py
│   │   │   ├── stages.py
│   │   │   └── registry.py
│   │   ├── stages/
│   │   │   ├── __init__.py
│   │   │   ├── chunk.py
│   │   │   ├── clean.py
│   │   │   ├── diagnose.py
│   │   │   ├── export.py
│   │   │   ├── extract_figures.py
│   │   │   ├── extract_tables.py
│   │   │   ├── extract_text.py
│   │   │   ├── ingest.py
│   │   │   ├── nlp.py
│   │   │   ├── ocr.py
│   │   │   └── validate.py
│   │   ├── plugins/
│   │   │   ├── ocr/
│   │   │   ├── tables/
│   │   │   └── figures/
│   │   └── __pycache__/
│   │       ├── __init__.cpython-312.pyc
│   │       ├── cli.cpython-312.pyc
│   │       └── ...
│   └── tests/  # (no existe actualmente)
├── docs/
│   ├── architecture.md
│   ├── pipeline.md
│   ├── cleaning_rules.md
│   ├── qa_metrics.md
│   └── resumenFaseUno.md
├── tools/
│   └── generate_summary_csv.py
├── README.md
├── .gitignore
├── pyproject.toml
└── configs/
    ├── default.yaml
    ├── codespaces.yaml
    ├── high_accuracy.yaml
    └── qa_thresholds.yaml
```
