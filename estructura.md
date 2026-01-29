## 6. Estructura de carpetas (robusta y escalable)

```
limpiatextos/
├── input_pdfs/                 # PDFs locales (gitignored)
├── workspace/                  # artefactos temporales (gitignored)
│   └── <doc_id>/
│       ├── manifest.json
│       ├── plan.json
│       ├── normalized.pdf
│       ├── raw_text_pages.jsonl
│       ├── clean_text.txt
│       ├── clean_text_pages.jsonl
│       ├── sections.json
│       ├── tables/
│       ├── tables_index.json
│       ├── figures/            # opcional
│       └── figures_index.json  # opcional
├── outputs/                    # resultados finales (gitignored)
│   ├── text/
│   ├── md/
│   ├── jsonl/
│   └── reports/
├── src/
│   ├── limpiatextos/
│   │   ├── __init__.py
│   │   ├── config/             # carga/validación config (YAML/TOML)
│   │   ├── core/               # contratos, modelos de datos, utilidades
│   │   │   ├── models.py        # Document, Page, Artifact, Metrics
│   │   │   ├── errors.py
│   │   │   └── logging.py
│   │   ├── pipeline/           # orquestación (DAG simple)
│   │   │   ├── runner.py
│   │   │   ├── stages.py        # definición de etapas
│   │   │   └── registry.py      # registro de plugins
│   │   ├── stages/
│   │   │   ├── ingest.py
│   │   │   ├── diagnose.py
│   │   │   ├── ocr.py
│   │   │   ├── extract_text.py
│   │   │   ├── extract_tables.py
│   │   │   ├── extract_figures.py  # opcional
│   │   │   ├── clean.py
│   │   │   ├── nlp.py
│   │   │   ├── chunk.py
│   │   │   ├── export.py
│   │   │   └── validate.py
│   │   ├── plugins/            # estrategias intercambiables
│   │   │   ├── ocr/
│   │   │   ├── tables/
│   │   │   └── figures/
│   │   └── cli.py              # interfaz CLI
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── fixtures/
├── docs/
│   ├── architecture.md
│   ├── pipeline.md
│   ├── cleaning_rules.md
│   └── qa_metrics.md
├── README.md
├── .gitignore
├── pyproject.toml
└── configs/
    ├── default.yaml
    ├── codespaces.yaml
    └── high_accuracy.yaml
```
