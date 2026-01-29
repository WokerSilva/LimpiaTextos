# LimpiaTextos — Limpieza y Normalización de PDFs para Agentes

## 1. Planteamiento del problema

En muchas áreas técnicas y operativas, el conocimiento clave vive en **manuales PDF**. Estos documentos suelen presentar varios problemas cuando se quieren usar en sistemas modernos de recuperación de información (RAG):

* PDFs con **capa de texto real** pero con layout complejo (múltiples columnas, saltos de línea artificiales, encabezados/pies repetidos).
* PDFs **escaneados** (solo imagen), donde el texto debe obtenerse mediante OCR.
* Presencia de **tablas**, que al extraerse como texto plano pierden estructura y significado.
* Texto fragmentado (palabras cortadas por guiones, párrafos rotos, saltos de línea incorrectos) que degrada severamente la calidad semántica.

El resultado típico es texto técnicamente extraído, pero **semánticamente roto**, lo cual afecta directamente la calidad de:

* la continuidad semántica
* la calidad de embeddings
* recuperación de contexto
* respuestas generadas por modelos LLM

Para RAG (y también para agentes GPT), **un texto limpio, continuo y bien normalizado es más valioso que el PDF original**.

---

## 2. Objetivo del proyecto

Construir una herramienta **robusta, escalable y extensible** para:

1. Ingerir PDFs heterogéneos.
2. Detectar el mejor método de extracción por página (texto/OCR).
3. Extraer texto + tablas + (opcional) figuras.
4. Aplicar limpieza/normalización **quirúrgica** sin romper el significado.
5. Producir salidas listas para indexación (txt/md/jsonl) con metadatos.

Este repositorio puede ser abierto (open-source) mientras:

* **inputs/outputs** permanezcan locales (via `.gitignore`)
* se documenten pipelines y configuraciones sin exponer datos

---

## 3. Principios de diseño

### 3.1 Diseño por etapas y artefactos (Data Pipeline)

* Pipeline **de extremo a extremo**, pero con etapas pequeñas e independientes.
* Cada etapa:

  * recibe un artefacto de entrada bien definido
  * produce un artefacto de salida validable
  * registra métricas/logs

### 3.2 Patrón plugin/strategy (Extensibilidad)

* OCR, extracción de tablas, extracción de texto y normalización se modelan como **estrategias** intercambiables.
* Un documento puede usar varias estrategias por página (híbrido).

### 3.3 Robustez operativa

* Configuración centralizada (YAML/TOML).
* Logging estructurado (JSON opcional), trazabilidad por `doc_id`.
* Reintentos controlados + aislamiento de fallas (un PDF fallido no tira todo el batch).

---

## 4. Stack de librerías (selección robusta)

### Core (estable, CPU-friendly)

* **OCRmyPDF**: normaliza PDFs y agrega capa de texto a escaneados.
* **pdfplumber**: extracción fina con awareness de layout.
* **tabula-py**: extracción de tablas (Java/Tabula) con buenos resultados en PDFs típicos.
* **textacy + spaCy**: segmentación y soporte NLP para normalización/validación.
* **ftfy**: reparación de problemas Unicode frecuentes.

### Opcionales (plugins, no obligatorios)

* **Camelot**: fallback para tablas cuando Tabula falla (activar bajo feature-flag).
* **pdffigures2**: extracción de figuras/captions como “plus” (cuando aplique).
* **docTR** o servicios cloud OCR: OCR avanzado (cuando el entorno lo permita).

---

## 5. Pipeline optimizado extremo a extremo

### Etapa A — Ingesta y registro

**Entrada**: PDF(s) en `input_pdfs/` (local, gitignored)

1. Generar `doc_id` (hash) por PDF.
2. Registrar metadatos (páginas, tamaño, nombre, timestamps).
3. Crear carpeta de trabajo por documento.

**Salida**: `workspace/<doc_id>/manifest.json`

---

### Etapa B — Diagnóstico y enrutamiento (router por página)

1. Detectar por página:

   * ¿hay texto suficiente?
   * ¿parece escaneo/imagen?
   * ¿hay señales de tablas?
2. Definir plan de ejecución por página:

   * `TEXT_EXTRACT`
   * `OCR`
   * `TABLE_EXTRACT`
   * `FIGURE_EXTRACT` (opcional)

**Salida**: `workspace/<doc_id>/plan.json`

---

### Etapa C — Normalización PDF (OCR si aplica)

* Ejecutar OCRmyPDF solo cuando sea necesario (o modo “estandarizar todo”, configurable).

**Salida**:

* `workspace/<doc_id>/normalized.pdf`
* métricas OCR (si disponibles)

---

### Etapa D — Extracción (texto/tablas/figuras)

#### Texto

* Extraer por página con pdfplumber.
* Extraer también “tokens” por bloques/bounding boxes cuando sea útil (para reconstruir orden).

**Salida**: `workspace/<doc_id>/raw_text_pages.jsonl` (1 línea = 1 página)

#### Tablas

* Usar tabula-py para páginas detectadas.
* Fallback opcional: Camelot.

**Salida**:

* `workspace/<doc_id>/tables/` (csv/json)
* `workspace/<doc_id>/tables_index.json`

#### Figuras (opcional)

* Extraer con pdffigures2 (si se activa el plugin).

**Salida**:

* `workspace/<doc_id>/figures/`
* `workspace/<doc_id>/figures_index.json`

---

### Etapa E — Limpieza y normalización

Aplicar transformaciones en un orden controlado:

1. Normalización Unicode (ftfy + unicodedata).
2. Eliminación de headers/footers repetidos (por frecuencia + posición).
3. Eliminación de números de página.
4. De-hyphenation (unir palabras cortadas).
5. Unión de líneas a párrafos (heurística: puntuación, minúscula/mayúscula, indentación, viudas/huérfanas).
6. Normalización de espacios y saltos de línea.

**Salida**:

* `workspace/<doc_id>/clean_text.txt`
* `workspace/<doc_id>/clean_text_pages.jsonl` (para trazabilidad)

---

### Etapa F — NLP y segmentación

* textacy/spaCy para re-sentencización.
* Identificación de títulos/secciones (heurísticas basadas en mayúsculas, numeración, patrones).

**Salida**:

* `workspace/<doc_id>/structured.md` (opcional)
* `workspace/<doc_id>/sections.json`

---

### Etapa G — Chunking y export para agentes

* Chunking por sección + tamaño (tokens/char) con overlap.
* Exportar JSONL con metadatos:

  * doc_id, source_filename
  * páginas origen
  * extraction_method por página
  * flags (tables_present, ocr_used)

**Salida**:

* `outputs/jsonl/<doc_id>.jsonl`
* `outputs/text/<doc_id>.txt`
* `outputs/md/<doc_id>.md` (opcional)

---

### Etapa H — QA / Validación

* Métricas por documento:

  * chars/page
  * ratio de líneas unidas
  * páginas vacías
  * tablas extraídas
  * señales de OCR pobre (si aplica)

**Salida**:

* `outputs/reports/summary.csv`
* `outputs/reports/<doc_id>.json`

---

## 7. Patrones de diseño aplicados

* **Strategy Pattern**: OCR/Table/Figure extractors reemplazables.
* **Registry/Plugin System**: agregar nuevos extractores sin tocar el core.
* **Pipeline por etapas**: cada stage es idempotente (si existe output, puede skip).
* **Data Contracts**: modelos `Document/Page/Artifact` para estandarizar entrada/salida.
* **Feature Flags**: activar Camelot, pdffigures2, etc. sin romper instalación base.

---

## 8. Reglas de privacidad / gitignore (recomendación)

`.gitignore` debe incluir siempre:

* `input_pdfs/`
* `workspace/`
* `outputs/`
* `*.pdf`
* `*.jsonl` (si contienen texto interno)

El repositorio queda seguro para compartir, mientras el procesamiento real se mantiene local.

---

## 9. Próximos pasos (documentación primero)

1. `docs/architecture.md`: justificar decisiones (CPU-first, plugins, artefactos).
2. `docs/cleaning_rules.md`: definir reglas de unión de líneas y de-hyphen.
3. `docs/pipeline.md`: ejemplo de ejecución end-to-end, con outputs.
4. `configs/codespaces.yaml`: configuración optimizada para CPU.
5. Definir un set mínimo de tests con PDFs sintéticos (fixtures).

---

**Meta**: que LimpiaTextos sea confiable, explicable y extensible.

Un buen pipeline no depende de una sola función: depende de contratos, etapas pequeñas y validación constante.
