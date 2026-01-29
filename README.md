# LimpiaTextos — Limpieza y Normalización de PDFs para Agentes

## 1. Planteamiento del problema

En muchas áreas técnicas y operativas, el conocimiento clave vive en **manuales PDF**. Estos documentos suelen presentar varios problemas cuando se quieren usar en sistemas modernos de recuperación de información (RAG):

* PDFs con **capa de texto real** pero con layout complejo (múltiples columnas, saltos de línea artificiales, encabezados/pies repetidos).
* PDFs **escaneados** (solo imagen), donde el texto debe obtenerse mediante OCR.
* Presencia de **tablas**, que al extraerse como texto plano pierden estructura y significado.
* Texto fragmentado (palabras cortadas por guiones, párrafos rotos, saltos de línea incorrectos) que degrada severamente la calidad semántica.

El resultado típico es texto técnicamente extraído, pero **semánticamente roto**, lo cual afecta directamente la calidad de:

* embeddings
* recuperación de contexto
* respuestas generadas por modelos LLM

Para RAG (y también para agentes GPT), **un texto limpio, continuo y bien normalizado es más valioso que el PDF original**.

---

## 2. Objetivo del proyecto

Construir una **herramienta abierta y reutilizable** que permita:

1. Ingerir PDFs heterogéneos (texto o imagen).
2. Extraer su contenido de forma confiable.
3. Aplicar un proceso de limpieza y normalización *quirúrgico*.
4. Generar salidas listas para indexación (txt / md / jsonl).

El foco **no** es entrenar modelos ni indexar directamente, sino entregar **texto de alta calidad**, optimizado para agentes.

---

## 3. Decisiones de diseño clave

### 3.1 Filosofía del pipeline

* Fases claras y desacopladas.
* Cada fase debe producir artefactos intermedios verificables.
* Fallbacks simples en lugar de heurísticas frágiles.

### 3.2 Repositorio abierto, datos privados

Se manejará mediante:

* `.gitignore` estricto (`outputs/`, `workspace/`, `input_pdfs/`).
* El repo contiene solo:

  * código
  * documentación
  * ejemplos sintéticos

---

## 4. Librerías seleccionadas 

### Núcleo del pipeline (selección final)

#### 1. OCRmyPDF

* Rol: normalización inicial de PDFs.
* Función:

  * Detectar si un PDF necesita OCR.
  * Aplicar OCR solo cuando es necesario.
  * Generar PDFs con capa de texto uniforme.
* Ventaja clave: evita reimplementar OCR y reduce errores.

#### 2. pdfplumber

* Rol: extracción de texto con conciencia de layout.
* Función:

  * Extraer texto por página y por regiones.
  * Permitir heurísticas para unir líneas correctamente.
* Ventaja clave: control fino sin usar DL.

#### 3. tabula-py **(principal para tablas)**

* Rol: extracción estructurada de tablas.
* Función:

  * Convertir tablas PDF a DataFrames / CSV / JSON.
* Ventaja clave:

  * Estable, probado, CPU-friendly.
  * Suficiente para la mayoría de manuales técnicos.

> Alternativa considerada pero no prioritaria: Camelot (útil, pero se evita duplicar dependencias al inicio).

#### 4. textacy (+ spaCy)

* Rol: normalización lingüística.
* Función:

  * Re-sentencización.
  * Validación de párrafos.
  * Apoyo para chunking semántico.
* Ventaja clave: mejora continuidad semántica tras limpieza.

---

## 5. Pipeline conceptual inicial

### Fase 0 — Ingesta

* Carpeta `input_pdfs/` (local, ignorada por git).
* Lectura de PDFs.
* Extracción de metadatos básicos (nombre, páginas).

---

### Fase 1 — Normalización del PDF

**Herramienta**: OCRmyPDF

* Detectar si el PDF tiene capa de texto útil.
* Si no la tiene → aplicar OCR.
* Salida:

  * PDF normalizado con capa de texto consistente.

Objetivo: que todos los PDFs se comporten igual aguas abajo.

---

### Fase 2 — Extracción de contenido

#### Texto

* Extraer texto por página con pdfplumber.
* Mantener orden lógico de lectura.
* Preservar saltos de párrafo (no unir todo todavía).

#### Tablas

* Detectar páginas con tablas.
* Usar tabula-py para extraerlas.
* Guardar tablas como:

  * CSV / JSON
  * Referenciadas por página.

---

### Fase 3 — Limpieza y normalización

Procesos aplicados:

* Normalización Unicode.
* Eliminación de encabezados y pies repetidos.
* Eliminación de números de página.
* De-hyphenation (unir palabras cortadas por salto de línea).
* Unión de líneas que pertenecen al mismo párrafo.
* Normalización de espacios y saltos.

Resultado: **texto continuo y legible**, no solo extraído.

---

### Fase 4 — Normalización lingüística

**Herramienta**: textacy / spaCy

* Re-sentencizar texto.
* Detectar párrafos inconsistentes.
* Preparar texto para chunking.

---

### Fase 5 — Salidas

Salidas finales (todas ignoradas por git):

* `outputs/text/` → texto completo por documento (`.txt`).
* `outputs/md/` → versión Markdown (opcional).
* `outputs/tables/` → tablas estructuradas (`.csv` / `.json`).
* `outputs/jsonl/` → chunks listos para RAG.
