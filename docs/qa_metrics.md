# QA Metrics — LimpiaTextos (v0)

## Objetivo

Definir métricas cuantificables, informes y umbrales para validar que cada PDF procesado por **LimpiaTextos** produce texto **semánticamente sano** y útil para RAG. Las métricas sirven para:

* Validación automática en la pipeline.
* Señalización de documentos que requieren revisión manual.
* Seguimiento histórico y regresión al cambiar reglas.

---

## Resumen de categorías de métrricas

1. **Extracción** — integridad de extracción por página.
2. **OCR (si aplica)** — calidad del OCR y confianza general.
3. **Limpieza** — cambios realizados (dehyphen, line joins, headers removidos).
4. **Tablas / Figuras** — cuántas detectadas y extraídas correctamente.
5. **NLP / Estructura** — sentencización y coherencia básica.
6. **Chunks / Export** — calidad de chunks para RAG.
7. **Global / Health** — métricas compuestas y flags de alerta.

Cada métrica tendrá: nombre, definición, fórmula (si aplica), umbral sugerido (configurable), acción si falla.

---

## 1) Extracción (por documento)

### 1.1 `pages_total`

* Descripción: número total de páginas del PDF (según meta o `pdfinfo`).
* Tipo: entero.

### 1.2 `pages_with_text_count`

* Descripción: páginas donde la extracción produjo > `min_chars_per_page` caracteres.
* Fórmula: contar páginas con `chars_on_page >= min_chars_per_page`.
* Umbral sugerido: `min_chars_per_page = 50` (configurable).
* Acción si falla: marcar doc para revisión si `pages_with_text_count / pages_total < 0.9` (es decir, menos del 90% de páginas tienen texto).

### 1.3 `chars_per_page_mean`

* Descripción: promedio de caracteres por página.
* Fórmula: (sumatorio de chars por página) / `pages_total`.
* Umbral: depende del tipo de manual; sugerido mínimo `chars_per_page_mean >= 200`.
* Acción: si muy bajo, indicar probable fallo OCR o extracción.

### 1.4 `pages_empty_ratio`

* Fórmula: `(pages_total - pages_with_text_count) / pages_total`.
* Umbral sugerido: `< 0.1` (menos de 10% páginas vacías).
* Acción: marcar para revisión si >= 0.1.

---

## 2) OCR (solo si se ejecutó OCR)

### 2.1 `ocr_used` (boolean)

* Indica si la pipeline aplicó OCR en el documento.

### 2.2 `ocr_pages_count`

* Número de páginas que pasaron por OCR.

### 2.3 `ocr_confidence_mean` (si disponible)

* Media de la confianza proporcionada por el OCR por palabra/línea (Tesseract no ofrece nativamente, pero `ocrmypdf` puede dar métricas o puedes estimar).
* Fórmula: promedio (conf_word_i) sobre todo el documento.
* Umbral sugerido: `>= 0.7` (70%) para considerar OCR confiable.
* Acción si falla: marcar doc para revisión; considerar re-procesar con parámetros distintos (deskew, despeckle) o usar servicio alternativo.

### 2.4 `ocr_low_confidence_pages`

* Lista/contador de páginas con confianza media por página < umbral (ej. 0.6).
* Acción: incluir en `report.samples` para revisión manual.

---

## 3) Limpieza (reglas aplicadas)

Estas métricas miden cuánto y cómo actuó la limpieza.

### 3.1 `dehyphen_joins`

* Número de uniones efectivas por de-hyphen.

### 3.2 `dehyphen_skips`

* Número de casos detectados pero no unidos (reglas conservadoras).

### 3.3 `line_joins`

* Número total de líneas concatenadas (3.6).

### 3.4 `header_lines_removed` / `footer_lines_removed`

* Conteo de líneas de header/footer eliminadas.

### 3.5 `line_join_ratio`

* Fórmula: `line_joins / total_lines`.
* Umbral: si `line_join_ratio > 0.6` (60% de líneas unidas) puede indicar unión excesiva; si `line_join_ratio < 0.01` puede indicar que no hubo reconstrucción.
* Acción: marcar para inspección si fuera de rango.

### 3.6 `changes_sample` (muestreo)

* Lista muestreada (por ejemplo 10 cambios) con estructuras `{page, before, after, rule}` para auditoría humana.

---

## 4) Tablas / Figuras

### 4.1 `tables_detected_count`

* Número de tablas detectadas por heurística/plan.

### 4.2 `tables_extracted_count`

* Número de tablas extraídas con éxito (CSV/JSON generados).

### 4.3 `tables_extraction_success_ratio`

* Fórmula: `tables_extracted_count / tables_detected_count` (si detector devuelve >0).
* Umbral sugerido: `>= 0.8` (80%) para la mayoría de manuales simples.
* Acción: si por debajo, registrar páginas con fallos y marcar para fallback (Camelot o detector DL).

### 4.4 `figures_detected_count` / `figures_extracted_count`

* Similar a tablas; para figuras extraídas con `pdffigures2`.

---

## 5) NLP / Estructura

### 5.1 `sentences_count`

* Número total de oraciones detectadas por spaCy.

### 5.2 `long_sentences_count`

* Oraciones con `tokens > long_sentence_token_thresh` (ej. 200 tokens).
* Acción: si hay muchas, puede indicar unión excesiva — añadir flag.

### 5.3 `short_sentences_ratio`

* Porcentaje de oraciones de ≤ 2 tokens.
* Umbral: si > 0.1 (10%) indica saltos excesivos → marcar.

### 5.4 `headings_detected_count`

* Número de headings/secciones detectadas.
* Acción: comparar contra expectativas (manuales estructurados suelen tener > X headings).

---

## 6) Chunks / Export

### 6.1 `chunks_count`

* Número de chunks generados.

### 6.2 `avg_chunk_tokens` / `avg_chunk_chars`

* Tamaño medio de chunk; objetivo: `avg_chunk_tokens ≈ 300–800` tokens (configurable).
* Acción si fuera de rango: ajustar parámetros de chunking.

### 6.3 `chunks_nonempty_ratio`

* Porcentaje de chunks con texto > `min_chars_chunk` (ej. 50 chars).
* Umbral: `>= 0.95`.

---

## 7) Global / Health

### 7.1 `doc_processing_time_seconds`

* Tiempo total de procesamiento del documento.

### 7.2 `stages_status` (map)

* Estado por stage: `OK`, `WARN`, `FAIL`. Ej:

  ```json
  {
    "ingest": "OK",
    "diagnose": "OK",
    "ocr": "WARN",
    "extract": "OK",
    "clean": "OK",
    "nlp": "OK",
    "chunk": "OK",
    "export": "OK",
    "validate": "OK"
  }
  ```

### 7.3 `overall_flag`

* `OK` / `REVIEW` / `FAIL` calculado por reglas:

  * `FAIL` si `pages_empty_ratio >= 0.5` o `ocr_used && ocr_confidence_mean < 0.4`.
  * `REVIEW` si alguna métrica está en zona sospechosa (ej. `line_join_ratio` fuera de rango, `tables_extraction_success_ratio < 0.6`).
  * `OK` en caso contrario.
* Estos umbrales son sugeridos y deben configurarse por `configs/*.yaml`.

---

## Reporte por documento (esquema JSON sugerido)

```json
{
  "doc_id": "sha256:abcd1234",
  "source_filename": "manual_001.pdf",
  "pages_total": 42,
  "pages_with_text_count": 40,
  "chars_per_page_mean": 1450,
  "pages_empty_ratio": 0.0476,
  "ocr_used": true,
  "ocr_pages_count": 10,
  "ocr_confidence_mean": 0.78,
  "dehyphen_joins": 124,
  "line_joins": 842,
  "header_lines_removed": 40,
  "tables_detected_count": 6,
  "tables_extracted_count": 6,
  "tables_extraction_success_ratio": 1.0,
  "sentences_count": 1245,
  "long_sentences_count": 12,
  "short_sentences_ratio": 0.03,
  "chunks_count": 98,
  "avg_chunk_chars": 3200,
  "stages_status": {
    "ingest": "OK",
    "diagnose": "OK",
    "ocr": "OK",
    "extract": "OK",
    "clean": "OK",
    "nlp": "OK",
    "chunk": "OK",
    "export": "OK",
    "validate": "OK"
  },
  "overall_flag": "OK",
  "processing_time_seconds": 123.4,
  "samples": [
    {
      "page": 3,
      "rule": "dehyphen",
      "before": "implemen- \n tación",
      "after": "implementación"
    }
  ]
}
```

> Nota: `pages_empty_ratio` calculado como `(pages_total - pages_with_text_count)/pages_total`. En el ejemplo: `(42 - 40) / 42 = 2/42 ≈ 0.047619...` (≈ 0.0476).

---

## CSV resumen de batch (columns sugeridas)

* doc_id
* source_filename
* pages_total
* pages_with_text_count
* pages_empty_ratio
* ocr_used
* ocr_confidence_mean
* tables_detected_count
* tables_extraction_success_ratio
* dehyphen_joins
* line_joins
* chunks_count
* overall_flag
* processing_time_seconds

---

## Umbrales sugeridos (configurables)

| Métrica                               | Umbral sugerido | Acción                     |
| ------------------------------------- | --------------: | -------------------------- |
| `pages_with_text_count / pages_total` |          >= 0.9 | OK                         |
| `pages_empty_ratio`                   |           < 0.1 | OK                         |
| `ocr_confidence_mean`                 |          >= 0.7 | OK                         |
| `tables_extraction_success_ratio`     |          >= 0.8 | OK                         |
| `line_join_ratio`                     |      0.01 — 0.6 | si fuera de rango → review |
| `chunks_nonempty_ratio`               |         >= 0.95 | OK                         |

---

## Acciones automáticas y alertas

* **Auto-retry OCR**: si `ocr_confidence_mean < 0.6`, reintentar OCR con opciones `--deskew --clean`.
* **Fallback table extractor**: si `tables_extraction_success_ratio < 0.6`, reintentar con Camelot o activar DL plugin.
* **Marcar para revisión**: si `overall_flag = REVIEW` o `FAIL`, añadir a `outputs/reports/to_review/` y notificar (log).
* **Muestreo**: guardar `N` ejemplos `before/after` para cada doc marcado `REVIEW` (para inspección humana).

---

## Tests automatizados sugeridos (CI)

1. **Unit tests**:

   * `test_dehyphen_join_valid_cases`
   * `test_dehyphen_skip_cases`
   * `test_header_footer_detection` con fixtures (simulate repeated header)
   * `test_line_join_rules` (bullets, titles)
2. **Integration (smoke)**:

   * Ejecutar pipeline MVP sobre 3 fixtures (simple text PDF, scanned PDF, multi-column with tables) y validar:

     * `pages_with_text_count / pages_total >= 0.9`
     * `tables_extraction_success_ratio >= 0.8` para fixtures que contienen tablas
3. **Regression**:

   * Snapshot `clean_text.txt` vs baseline para detectar cambios inesperados en reglas de limpieza.

---

## Dashboard / Observabilidad (opcional)

* Guardar `outputs/reports/summary.csv` y montar un dashboard (Grafana / Superset / simple Jupyter) con:

  * tasa de fallos por día
  * histogramas de `chars_per_page_mean`
  * tendencia de `ocr_confidence_mean`
  * documentos en `to_review`

---

## Implementación en la pipeline

* Cada stage que transforma datos debe emitir métricas parciales (ej. `clean` emite `dehyphen_joins`, `line_joins`).
* Runner agrega métricas en `reports/<doc_id>.json` al final del flujo.
* Validación final calcula `overall_flag` según reglas configurables.

---

## Notas finales y recomendaciones

* Los umbrales aquí son **sugeridos**; ajusta según tu corpus real tras un POC con 20–50 manuales.
* Prioridad práctica:

  1. Asegura que las métricas básicas de extracción y OCR están saneadas (pages/ocr).
  2. Afina reglas de dehyphen y line_join con ejemplos reales hasta lograr `line_join_ratio` estable.
  3. Implementa muestreo `before/after` para comunicar mejoras y para debugging.
* Mantén todas las métricas versionadas junto con `config_hash` para reproducibilidad.
