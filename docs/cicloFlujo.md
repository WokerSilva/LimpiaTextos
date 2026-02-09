# LimpiaTextos — Pipeline de limpieza y seccionado para RAG (PDF → MD + QA)

Este repositorio transforma PDFs corporativos (manuales/políticas) en Markdown utilizable para RAG, con:
- extracción de texto por página,
- limpieza (pies de página/encabezados/ruido),
- seccionado y normalización,
- detección de tablas (en progreso),
- generación de outputs por lote (agent_corpus),
- empaquetado de Markdown en “chunks” grandes listos para subir a agentes (agent-pack),
- métricas y QA.

---

## 1) Estructura de carpetas (visión rápida)

### Entradas
- `input_pdfs/`  
  PDFs locales (típicamente gitignored)
- `input_batches/<lote>/pdfs/`  
  PDFs por lote para estrategia `agent_corpus`

### Temporales (por documento)
- `workspace/<doc_id>/`  
  Todo lo que se genera durante el pipeline para cada PDF
  - `raw_text_pages.jsonl` (por página, antes de limpieza)
  - `agent/`
    - `meta.json` (señales: footer, doc_code, version, etc.)
    - `pages_clean.jsonl` (por página ya limpio)
    - `tables.json` (tablas detectadas, si aplica)

### Salidas
- `outputs/agent_corpus/<lote>/`
  - `md/` (MD por documento)
  - `corpus.md` (concatenado de todos los MD del lote)
  - `corpus_index.json` (índice/metadata de lote)
  - `batch_report.json` (reporte de ejecución)
  - `agent_packages/` (salida del empaquetador `agent-pack`)

---

## 2) Flujo de proceso (end-to-end)

### A) Ejecutar por lote: generar MD por PDF
1) Preparas PDFs:
```

input_batches/lote_04/pdfs/*.pdf

````

2) Corres estrategia:
```bash
limpiatextos agent-corpus input_batches/lote_04
````

Esto:

* recorre PDFs del lote,
* ejecuta `run_document()` por PDF (pipeline),
* produce artefactos en `workspace/<doc_id>/...`,
* renderiza un `.md` por doc en `outputs/agent_corpus/<lote>/md/`,
* genera un `corpus.md` concatenando todos.

### B) Empaquetar MD para agentes (por tamaño máximo)

Cuando ya tienes todos los `.md` del lote:

```bash
limpiatextos agent-pack lote_04 --max-mb 20
```

Esto:

* toma `outputs/agent_corpus/lote_04/md/*.md`,
* genera paquetes `agent_package_001.md`, `agent_package_002.md`, etc. en:

  ```
  outputs/agent_corpus/lote_04/agent_packages/
  ```
* corta cuando el archivo se acerca al tamaño max (`--max-mb`), usando un umbral de seguridad (por defecto ~98%).

---

## 3) Comandos y utilidades (catálogo completo)

### 3.1 Comandos CLI del proyecto

#### `limpiatextos agent-corpus <batch_dir>`

**Propósito:** ejecutar un lote de PDFs y generar:

* MD por documento
* `corpus.md` por lote
* índices y reportes

**Ejemplo:**

```bash
limpiatextos agent-corpus input_batches/lote_01
limpiatextos agent-corpus input_batches/lote_04
```

**Dónde lee:**

* `input_batches/<lote>/pdfs/*.pdf`

**Dónde escribe:**

* `workspace/<doc_id>/...`
* `outputs/agent_corpus/<lote>/md/*.md`
* `outputs/agent_corpus/<lote>/corpus.md`
* `outputs/agent_corpus/<lote>/corpus_index.json`
* `outputs/agent_corpus/<lote>/batch_report.json`

---

#### `limpiatextos run ...` (pipeline general)

**Propósito:** ejecutar pipeline sobre un PDF (modo “run” del pipeline base).

> Nota: dependiendo tu CLI actual, los flags exactos pueden variar; la idea es que esto corre el pipeline “core”.

---

#### `limpiatextos summary ...`

**Propósito:** generar resumen/reportes (si está implementado).

---

#### `limpiatextos agent-pack <lote_id> --max-mb <N>`

**Propósito:** empaquetar todos los `.md` del lote en archivos grandes que no excedan el tamaño máximo.

**Ejemplo:**

```bash
limpiatextos agent-pack lote_04 --max-mb 20
```

**Dónde lee:**

* `outputs/agent_corpus/<lote>/md/*.md`

**Dónde escribe:**

* `outputs/agent_corpus/<lote>/agent_packages/*.md`

---

### 3.2 Comandos de diagnóstico (los que se usaron para validar)

#### Buscar archivos meta y páginas limpias en workspace

```bash
find workspace -path "*agent/meta.json" -print
find workspace -path "*agent/pages_clean.jsonl" -print
```

**Sirve para:** confirmar que el pipeline está generando artefactos por documento.

---

#### Validar si el pie de página fue removido en la versión limpia (pages_clean)

```bash
grep -R "CÓDIGO:" -n workspace/*/agent/pages_clean.jsonl || true
```

**Interpretación:**

* Si NO sale nada → el pie fue removido de `pages_clean.jsonl`.
* Si sale → aún se está colando y hay que ajustar reglas.

---

#### Ver metadatos detectados (doc_code, versión, fecha…)

```bash
cat workspace/*/agent/meta.json
```

**Sirve para:** verificar que el “footer parser” detectó y guardó:

* `doc_code`, `raw_date`, `version`, `classification`, etc.

---

#### Validar si el pie de página se coló en outputs finales

```bash
grep -R "CÓDIGO:" outputs/agent_corpus/lote_01 -n || true
```

**Sirve para:** confirmar si el render final MD aún contiene el footer (bug en render / runner).

---

#### Compilar módulo para cazar errores de sintaxis/imports

```bash
python -m compileall src/limpiatextos/stages/agent_detect_tables.py
```

**Sirve para:** detectar:

* `from __future__ import ...` mal ubicado,
* sintaxis inválida,
* errores de import.

---

#### Instalar en editable para que el CLI vea los módulos nuevos

```bash
pip install -e .
```

**Sirve para:** que `limpiatextos` encuentre módulos recién creados (ej. `pack_agent_md.py`).

---

## 4) Artefactos clave (qué son y por qué importan)

### 4.1 `raw_text_pages.jsonl` (por documento)

**Generado por:** `ExtractTextStage` (pypdf)
**Contenido:** líneas NDJSON:

```json
{"page": 1, "text": "..."}
{"page": 2, "text": "..."}
```

**Uso:** base “cruda” para limpieza posterior.

> En tu repo no existe un `raw_text.txt`; el equivalente práctico es este JSONL por página.

---

### 4.2 `workspace/<doc_id>/agent/pages_clean.jsonl`

**Generado por:** etapa “agent clean” (tu pipeline agente)
**Contenido:** texto por página ya con limpieza aplicada:

* pie removido,
* encabezados removidos,
* ruido recortado,
* (y eventualmente: normalización de saltos de línea).

---

### 4.3 `workspace/<doc_id>/agent/meta.json`

**Generado por:** parser de footer/header
**Ejemplo (real):**

```json
{
  "footer_detected": true,
  "doc_code": "M14.P02.S02.001.C",
  "raw_date": "12/12/2025",
  "version": "5.0",
  "classification": "INTERNO",
  "pages_total": 20,
  "footer_lines_removed": 19,
  "headers_lines_removed": 23
}
```

**Uso:**

* alimentar YAML front-matter futuro,
* QA,
* trazabilidad (sin perder data aunque se elimine del cuerpo).

---

### 4.4 `workspace/<doc_id>/agent/tables.json`

**Generado por:** `AgentDetectTablesStage` (heurística)
**Uso:**

* Guardar tablas detectadas (bitácora, responsabilidades, indicadores…)
* Luego el renderer puede “inyectarlas” como Markdown real.

> Ojo: detectar ≠ renderizar. Si `tables.json` existe pero “no se ve tabla” en el MD, el bug suele estar en el **renderizador** (runner) o en el “injection logic”.

---

## 5) Problemas conocidos (y cómo los atacamos)

### 5.1 “El footer no aparece en pages_clean pero sí en el MD final”

Esto indica:

* la limpieza funciona en `pages_clean.jsonl`,
* pero el MD final se está renderizando desde otra fuente (o se está inyectando texto extra).

**Acción típica:**

* asegurarte de que el runner *solo* renderiza desde `agent/pages_clean.jsonl`,
* y que el “footer” (si lo quieres “una vez”) se agregue como bloque final separado, no mezclado con el cuerpo.

---

### 5.2 Tablas detectadas pero no aparecen como tabla Markdown

Causas típicas:

* `tables.json` tiene filas “sucias” (colapsadas en una sola celda),
* o no hay columnas (`columns: []`), por lo que el renderer hace fallback,
* o el runner imprime un bloque “Tablas detectadas” al inicio (debug) y NO inyecta en su ubicación correcta.

**Estrategia objetivo:**

* “Render en sitio”: cuando se detecta un título de sección (Bitácora), insertar la tabla ahí,
* “Skip-mode”: saltarse el bloque textual original (texto plano) para evitar duplicado,
* “Stop-phrases”: cortar contaminación (“11. Procedimiento…”) dentro de celdas.

---

### 5.3 Saltos de línea dentro de frases (“Encargado de optimización / y mejora”)

Riesgo: pérdida semántica al chunkear/indexar.

**Estrategia recomendada:**

* unir “soft breaks” SOLO en `body_text`,
* NO tocar saltos en:

  * tablas,
  * listas,
  * headings.

(Esto se implementa como una etapa de normalización posterior a limpieza y antes de render.)

---

## 6) QA mínimo recomendado (checks automáticos)

* Footer:

  * `grep -R "CÓDIGO:" workspace/<doc_id>/agent/pages_clean.jsonl` debe dar 0 matches.
* MD final:

  * `grep -R "CÓDIGO:" outputs/agent_corpus/<lote>/md` debe dar 0 matches (o 1 si decides inyectarlo “una vez” explícitamente).
* Tablas:

  * si `tables.json` contiene `type: bitacora_cambios` con filas ⇒ el MD debe tener un bloque con `| No. | Versión | ... |`.
* Contaminación:

  * dentro de bitácora no debe aparecer `Procedimiento`, `Objetivo`, `Alcance` como parte de una celda.

---

## 7) Referencias internas del repo (documentación)

* `Architecture.md`
* `Pipeline.md`
* `Cleaning Rules.md`
* `QA Metrics.md`
* `Estructura.md`
* `resumenFaseInicial.md`

---

## 8) Ejemplos rápidos

### Ejecutar lote

```bash
limpiatextos agent-corpus input_batches/lote_04
```

### Validar outputs

```bash
ls outputs/agent_corpus/lote_04/md
cat outputs/agent_corpus/lote_04/corpus.md | head -n 50
```

### Empaquetar para agentes

```bash
limpiatextos agent-pack lote_04 --max-mb 20
ls outputs/agent_corpus/lote_04/agent_packages
```

````

---

### Para que quede PERFECTO “con todos los comandos que hemos usado”
Si quieres que el README quede 100% fiel “tal cual” a tu historial real (sin aproximaciones), lo ideal es que me pegues el output de:

```bash
history | tail -n 200
````

(o el rango que quieras, por ejemplo de la sesión actual). Con eso te lo dejo literal, **comando por comando**, y lo clasifico por etapa (instalación, ejecución, QA, debug, etc.) sin inventar ninguno.
