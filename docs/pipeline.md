# Pipeline — LimpiaTextos (v0)

Este documento describe el pipeline **end-to-end** de LimpiaTextos, con enfoque de ingeniería de datos:

* etapas desacopladas
* artefactos intermedios trazables
* idempotencia (re-ejecución sin rehacer trabajo)
* extensibilidad por plugins/estrategias

La meta: convertir PDFs en **texto limpio y estructurado** listo para RAG, sin depender de servicios externos.

---

## 1) Vista general

### Diagrama lógico (etapas)

1. **Ingest** → registro y `doc_id`
2. **Diagnose/Route** → plan por documento/página
3. **Normalize PDF (OCR)** → estandarización con OCRmyPDF
4. **Extract** → texto/tablas/(figuras)
5. **Clean** → reglas quirúrgicas (ver `Cleaning Rules`)
6. **NLP/Structure** → sentencización + títulos/secciones
7. **Chunk** → chunks listos para embeddings
8. **Export** → txt/md/jsonl + tablas/figuras
9. **Validate/QA** → métricas, flags, reportes

Cada etapa:

* lee artefactos previos
* escribe artefactos nuevos
* registra métricas

---

## 2) Contratos de datos (artefactos)

### 2.1 Nombres y formato

* Los artefactos viven en `workspace/<doc_id>/...`.
* **JSONL** se usa cuando el contenido es por página o por chunk.
* **JSON** se usa para manifests, planes y reportes.

### 2.2 Artefactos por etapa (resumen)

| Etapa                 | Entrada                  | Salida                                     | Objetivo                     |
| --------------------- | ------------------------ | ------------------------------------------ | ---------------------------- |
| Ingest                | PDF                      | `manifest.json`                            | Identidad y metadata         |
| Diagnose              | `manifest.json`          | `plan.json`                                | Plan de ejecución por página |
| OCR                   | PDF                      | `normalized.pdf`                           | Uniformizar capa texto       |
| Extract text          | `normalized.pdf`         | `raw_text_pages.jsonl`                     | Texto por página             |
| Extract tables        | `normalized.pdf`         | `tables/*`, `tables_index.json`            | Tablas estructuradas         |
| Extract figures (opt) | `normalized.pdf`         | `figures/*`, `figures_index.json`          | Assets + captions            |
| Clean                 | `raw_text_pages.jsonl`   | `clean_text_pages.jsonl`, `clean_text.txt` | Continuidad semántica        |
| NLP                   | `clean_text_pages.jsonl` | `sections.json`, `structured.md`           | Segmentación y estructura    |
| Chunk                 | `sections.json` o texto  | `chunks.jsonl`                             | Unidades para RAG            |
| Export                | artefactos previos       | `outputs/*`                                | Salidas finales              |
| Validate              | todos                    | `reports/*`                                | QA y métricas                |

---

## 3) Idempotencia y re-ejecución

Principio: **si un artefacto de salida existe y es válido, la etapa puede skip**.

### 3.1 Reglas de idempotencia (por etapa)

* Ingest: si `manifest.json` existe y `checksum` del PDF coincide → skip.
* Diagnose: si `plan.json` existe y la versión de config no cambió → skip.
* OCR: si `normalized.pdf` existe y coincide con `plan.json` → skip.
* Extract: si outputs existen y `normalized.pdf` no cambió → skip.
* Clean/NLP/Chunk: si inputs y config version no cambiaron → skip.

### 3.2 Versionado de config

En cada artefacto clave (manifest/plan/report), incluir:

* `pipeline_version`
* `config_hash`

Esto permite reproducibilidad y evita resultados mezclados.

---

## 4) Orquestación del pipeline

### 4.1 Runner (modo batch)

El pipeline corre por lotes:

* recorre PDFs en `input_pdfs/`
* ejecuta por documento
* registra fallas aisladas

Características:

* **fail-soft**: un PDF fallido no detiene el batch.
* **retry controlado**: reintentos en etapas frágiles (OCR/extract).
* **concurrency moderada** (CPU): configurable (ej. 1–2 docs en paralelo en Codespaces).

### 4.2 DAG simple

Aunque internamente se piense como DAG, al inicio basta con un pipeline lineal por doc:

* ingest → diagnose → ocr → extract → clean → nlp → chunk → export → validate

Para extensibilidad:

* `stages` se registran en un `registry`.
* los plugins se configuran en YAML.

---

## 5) Router y estrategias (Strategy Pattern)

### 5.1 Router por documento y por página

El router decide:

* si el documento requiere OCR
* qué páginas se procesan como:

  * texto directo
  * OCR
  * tablas
  * figuras (opcional)

**Salida**: `plan.json`

Ejemplo conceptual (plan):

* `doc_requires_ocr: true`
* `pages:`

  * `1: [TEXT_EXTRACT]`
  * `2: [TEXT_EXTRACT, TABLE_EXTRACT]`
  * `3: [OCR, TEXT_EXTRACT]`

### 5.2 Estrategias (plugins)

* OCRStrategy:

  * `ocrmypdf_tesseract`
  * (opcional) `doctr`

* TableStrategy:

  * `tabula`
  * (opcional) `camelot`

* FigureStrategy (opt):

  * `pdffigures2`

Esto permite:

* cambiar herramientas sin tocar el core
* mantener instalación base liviana

---

## 6) Detalle por etapa (qué hace y cómo valida)

### 6.1 Ingest

**Hace**:

* calcula `doc_id` (hash)
* extrae metadata básica (páginas, tamaño)
* crea `workspace/<doc_id>/`

**Valida**:

* PDF legible
* páginas > 0

**Artefacto**:

* `manifest.json`

---

### 6.2 Diagnose/Route

**Hace**:

* detecta si hay capa de texto útil
* detecta señales de escaneo (poco texto)
* detecta páginas con tablas (heurística rápida)

**Valida**:

* produce `plan.json` consistente

---

### 6.3 Normalize PDF (OCR)

**Hace**:

* corre OCRmyPDF si aplica (configurable: `skip_text`, `force_ocr`)

**Valida**:

* `normalized.pdf` existe
* páginas coinciden con input

---

### 6.4 Extract

#### Extract text

**Hace**:

* extrae texto por página (`pdfplumber`)
* (opcional) extrae bloques/bboxes si `layout.multicolumn.use_bboxes=true`

**Valida**:

* texto no vacío en la mayoría de páginas (umbral)

**Artefacto**:

* `raw_text_pages.jsonl`

#### Extract tables

**Hace**:

* extrae tablas en páginas marcadas
* genera índice con page→table assets

**Valida**:

* si se marcó tabla pero no se extrajo nada, registrar warning

**Artefactos**:

* `tables/*.csv|json`
* `tables_index.json`

#### Extract figures (opcional)

**Hace**:

* extrae assets + captions

**Valida**:

* registra conteo de figuras

---

### 6.5 Clean

**Hace**:

* aplica reglas de `Cleaning Rules` en orden
* preserva trazabilidad por página

**Valida**:

* ratio de páginas vacías bajo
* ratio line_joins razonable

**Artefactos**:

* `clean_text_pages.jsonl`
* `clean_text.txt`

---

### 6.6 NLP/Structure

**Hace**:

* sentencización con spaCy
* detección de headings/secciones
* (opcional) generar `structured.md`

**Valida**:

* no exceso de oraciones ultra largas o ultra cortas

**Artefactos**:

* `sections.json`
* `structured.md` (opcional)

---

### 6.7 Chunk

**Hace**:

* chunking por sección (preferido)
* fallback: chunking por tamaño (tokens/char)
* overlap configurable

**Valida**:

* chunks no vacíos
* distribución de tamaño razonable

**Artefacto**:

* `chunks.jsonl`

---

### 6.8 Export

**Hace**:

* copia/compone outputs finales en `outputs/`
* aplica naming consistente

**Salidas**:

* `outputs/text/<doc_id>.txt`
* `outputs/md/<doc_id>.md` (opcional)
* `outputs/jsonl/<doc_id>.jsonl`
* `outputs/tables/<doc_id>/*` (si aplica)
* `outputs/figures/<doc_id>/*` (si aplica)

---

### 6.9 Validate/QA

**Hace**:

* genera métricas por documento
* genera resumen batch

**Métricas recomendadas**:

* `pages_total`, `pages_empty`
* `chars_per_page_mean`
* `line_joins`
* `headings_detected`
* `tables_extracted_count`
* `ocr_used`

**Artefactos**:

* `outputs/reports/<doc_id>.json`
* `outputs/reports/summary.csv`

---

## 7) Configuración por entorno (Codespaces vs alta precisión)

### 7.1 `configs/codespaces.yaml`

* concurrencia baja (1–2 docs)
* OCR conservador (solo cuando falta texto)
* plugins opcionales desactivados (figures, DL)

### 7.2 `configs/high_accuracy.yaml`

* activar fallbacks (Camelot)
* activar extracción de figuras (pdffigures2)
* activar bbox-based extraction si multi-columna

---

## 8) CLI y experiencia de usuario

Comandos esperados (conceptual):

* `limpiatextos run --config configs/codespaces.yaml`
* `limpiatextos run --input input_pdfs --output outputs`
* `limpiatextos validate --doc <doc_id>`
* `limpiatextos clean-only --doc <doc_id>`

La CLI debe:

* imprimir progreso
* escribir logs
* devolver exit codes correctos

---

## 9) Criterios de éxito

El pipeline se considera exitoso si:

* el texto resultante mantiene ideas completas
* reduce ruido (headers/pies)
* mejora continuidad (menos saltos artificiales)
* produce chunks coherentes
* es reproducible (config_hash)

---