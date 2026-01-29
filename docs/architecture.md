# Architecture — LimpiaTextos

Este documento describe la **arquitectura técnica** del proyecto desde la perspectiva de ingeniería de datos + AI. Está pensado para que un equipo (o tú) pueda **implementar, mantener y escalar** LimpiaTextos con claridad: componentes, contratos, pautas de diseño, extensibilidad y prácticas operativas.

---

## 1. Visión general (otra vez, en una línea)

LimpiaTextos transforma PDFs en **artefactos textuales limpios y trazables** listos para indexar en RAG, mediante un pipeline modular, idempotente y extensible con plugins. Prioridad: **robustez**, **reproducibilidad** y **ejecución offline** (Codespaces / CPU).

---

## 2. Componentes principales (high-level)

* **CLI / Runner** (`src/limpiatextos/cli.py`, `runner.py`)
  Punto de entrada: orquesta pipeline por documento/lote, lee config y dispara stages.

* **Registry / Plugin Manager** (`registry.py`)
  Registro dinámico de estrategias (OCR, TableExtractors, FigureExtractors). Permite swapear implementaciones sin tocar core.

* **Stages** (`src/limpiatextos/stages/*.py`)
  Implementaciones atómicas de cada paso (ingest, diagnose, ocr, extract_text, extract_tables, clean, nlp, chunk, export, validate). Cada stage:

  * recibe artefactos definidos (contrato)
  * produce artefactos (contrato)
  * es idempotente (si output válido existe → skip)

* **Core models & contracts** (`core/models.py`)
  Tipos de datos: `Document`, `Page`, `Artifact`, `Plan`, `Metrics`. Central para compatibilidad entre stages/plugins.

* **I/O layer** (`io_utils.py`)
  Gestión de workspace, atomic writes, checksum, locks (simple file-lock para evitar race conditions).

* **Config** (`configs/*.yaml`)
  Configuración por entorno, feature flags, thresholds. Versionado y hashing para reproducibilidad.

* **Plugins** (`src/limpiatextos/plugins/*`)
  Carpetas: `ocr/`, `tables/`, `figures/`. Cada plugin implementa una interfaz (ver sección Interfaces).

* **Tests** (`src/tests/`)
  Unit + integration con fixtures sintéticos que simulan PDFs variados.

* **Docs / Reports** (`docs/`, `outputs/reports/`)
  Artefactos legibles para QA y auditoría.

---

## 3. Principios y patrones aplicados

* **Single Responsibility**: cada stage hace una tarea concreta y pequeño.
* **Strategy / Plugin pattern**: OCR, Table, Figure extractors son intercambiables.
* **Registry**: centraliza plugins y versiones.
* **Idempotency**: outputs determinan si volver a correr etapa.
* **Data Contracts**: JSON/JSONL estandarizados para todos los artefactos.
* **Fail-soft**: errores aislados por documento; batch continúa.
* **Config-driven**: comportamiento controlado por `configs/*.yaml`.
* **Observability**: logs estructurados + métricas por documento.

---

## 4. Contratos de artefactos (ejemplos JSON)

### `manifest.json`

```json
{
  "doc_id": "sha256:abcd...",
  "source_filename": "manual_x.pdf",
  "pages": 42,
  "checksum": "sha256:...",
  "pipeline_version": "0.1.0",
  "config_hash": "sha256:..."
}
```

### `plan.json` (router)

```json
{
  "doc_id": "...",
  "doc_requires_ocr": true,
  "pages": {
    "1": ["TEXT_EXTRACT"],
    "2": ["TABLE_EXTRACT", "TEXT_EXTRACT"],
    "5": ["OCR", "TEXT_EXTRACT"]
  },
  "created_at": "2026-01-29T12:00:00Z"
}
```

### `raw_text_pages.jsonl`

Cada línea: `{ "doc_id": "...", "page": 1, "text": "..." , "blocks": [...], "extraction_method": "pdfplumber" }`

### `clean_text_pages.jsonl`

Cada línea: `{ "doc_id":"...", "page":1, "text":"cleaned text...", "transformations":[{"rule":"dehyphen","changed":true}], "metrics":{}}`

---

## 5. Interfaces (plugin contract examples)

### OCRStrategy (abstract)

```py
class OCRStrategy(ABC):
    name: str

    @abstractmethod
    def needs_ocr(page_image: Path, heuristics: dict) -> bool:
        """Decide si aplicar OCR en una página"""

    @abstractmethod
    def run_ocr(input_pdf: Path, output_pdf: Path, options: dict) -> dict:
        """Ejecuta OCR a nivel documento, devuelve métricas"""
```

Implementación por defecto: `ocrmypdf_tesseract` (usa subprocess para llamar ocrmypdf + tesseract).

---

### TableExtractor

```py
class TableExtractor(ABC):
    name: str

    @abstractmethod
    def detect_tables(page_image_or_pdf: Path) -> List[BoundingBox]:
        """Detecta bounding boxes de tablas"""

    @abstractmethod
    def extract_table(page_pdf: Path, bbox: BoundingBox) -> DataFrame:
        """Extrae DataFrame"""
```

Implementaciones: `tabula_py`, `camelot`, `cascade_tabnet_adapter` (plugin opcional).

---

### FigureExtractor (opcional)

```py
class FigureExtractor(ABC):
    def detect_figures(...)
    def extract_figure(...)
    def classify_figure_type(image) -> Enum(chart, diagram, photo)
```

Implementación: `pdffigures2_adapter`.

---

## 6. Flujos y secuencias (texto)

### Batch run (simplificado)

1. Runner detecta PDFs en `input_pdfs/`.
2. Por cada PDF:

   * `ingest` → `manifest.json`
   * `diagnose` → `plan.json`
   * Si `plan` indica OCR → `ocr` (produce `normalized.pdf`)
   * `extract_text` → `raw_text_pages.jsonl`
   * `extract_tables` → `tables/`
   * `clean` → `clean_text_pages.jsonl`, `clean_text.txt`
   * `nlp` → `sections.json`
   * `chunk` → `chunks.jsonl`
   * `export` → `outputs/...`
   * `validate` → `reports/<doc_id>.json`

### Error handling

* Cada stage captura excepciones y añade `error` en `reports/<doc_id>.json` sin abortar el batch.
* Reintentos configurables (e.g., OCR 2 intentos).

---

## 7. Diseño para Codespaces (constraints)

* **Concurrencia**: default 1 doc en paralelo, configurable `runner.concurrency`.
* **Dependencias**: mantener núcleo liviano; plugins pesados opcionales y documentados.
* **No GPU**: DL plugins etiquetados como "experimental" y off por defecto.
* **Instalación**: `devcontainer.json` con scripts para instalar Tesseract, Java (Tabula), Poppler.

---

## 8. Observabilidad y QA

* **Logging**: JSON logs por stage con `doc_id`, `page`, `stage`, `duration_ms`, `status`.
* **Reports**: `outputs/reports/<doc_id>.json` con métricas (chars/page, pages_empty, dehyphen_count, headers_removed, ocr_used).
* **Batch summary**: `outputs/reports/summary.csv`.
* **Sample audit**: guardar n muestras `before/after` por doc para revisión manual.
* **Alerting**: si `pages_empty` > threshold → flag para revisión.

---

## 9. Seguridad & Privacidad

* `.gitignore` estricto (input_pdfs, workspace, outputs).
* No telemetría ni llamadas externas por defecto.
* Opciones para desactivar cualquier plugin que contactaría servicios externos.
* Recomendación: ejecutar en red aislada y con policies de acceso a discos.

---

## 10. Testing strategy

* **Unit tests**: reglas de limpieza (dehyphen, join lines, header detection).
* **Integration tests**: correr pipeline sobre fixtures PDF sintéticos (multi-columna, tablas, imágenes), verificar artefactos.
* **Regression**: snapshot tests `clean_text.txt` vs baseline.
* **CI**: GitHub Actions que instalan deps mínimos + ven run de smoke tests con fixtures (no reales).

---

## 11. CI / CD y releases

* **CI jobs**:

  * Linting (flake8/isort), formatting (black)
  * Unit tests
  * Integration smoke tests (fixtures)
  * Build package (wheel)
* **Releases**: versionado semántico; incluir changelog con `pipeline_version`.
* **Publishing**: código open-source; no publicar artifacts que contengan outputs o fixtures reales.

---

## 12. Roadmap de extensibilidad (próximos plugins y mejoras)

* `cascade_tabnet_adapter` para tablas como imágenes.
* `doctr_adapter` o `docTR` como OCR DL (GPU opt-in).
* `chart_ocr` plugin para extraer series de gráficos.
* Servicio REST simple para procesar un PDF (privado/interno) cuando se requiera integración.
* Integración opcional con vector DB (Qdrant/Pinecone) desde `export` (plugin).

---

## 13. Ejemplo de estructura de carpetas del paquete (recap)

```
src/limpiatextos/
├── __init__.py
├── cli.py
├── config/
├── core/
│   ├── models.py
│   ├── logging.py
│   └── errors.py
├── pipeline/
│   ├── runner.py
│   ├── registry.py
│   └── stages.py
├── stages/
│   ├── ingest.py
│   ├── diagnose.py
│   ├── ocr.py
│   ├── extract_text.py
│   ├── extract_tables.py
│   ├── clean.py
│   ├── nlp.py
│   ├── chunk.py
│   └── export.py
├── plugins/
│   ├── ocr/
│   ├── tables/
│   └── figures/
└── tests/
    ├── unit/
    └── integration/
```

---

## 14. Recomendaciones finales (operativas)

* Empezar con la **implementación mínima viable** (MVP):

  * OCRmyPDF + pdfplumber + tabula-py + ftfy + textacy
  * Stages idempotentes y el registry en modo simple
  * Fixtures y tests
* Documentar bien `configs/codespaces.yaml` para facilitar onboarding.
* Añadir muestras `before/after` en `reports/` para comunicar mejoras.
* Mantener plugins pesados fuera del install por defecto (extra requirements).