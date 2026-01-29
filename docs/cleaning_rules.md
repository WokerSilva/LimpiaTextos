# Cleaning Rules — LimpiaTextos (v0)

Este documento define las **reglas de limpieza y normalización quirúrgica** para convertir texto extraído de PDF (texto u OCR) en contenido **semánticamente continuo** y listo para RAG.

La meta no es “texto bonito”: es **texto fiel**, donde las ideas se preservan, los párrafos quedan coherentes y el ruido típico de PDF/OCR se minimiza.

---

## 0) Principios

1. **No destruir información**: preferimos conservar algo “de más” antes que borrar contenido válido.
2. **Trazabilidad**: cada transformación debe poder auditarse (idealmente por página).
3. **Orden importa**: aplicar reglas en el orden correcto evita efectos secundarios.
4. **Configurable**: todo threshold/regla debe poder ajustarse por `configs/*.yaml`.
5. **Fail-soft**: si una regla no puede decidir, deja el texto sin cambios y marca un flag.

---

## 1) Entradas y salidas esperadas

### Entrada mínima

* Texto por página (ideal): `raw_text_pages.jsonl` con:

  * `doc_id`, `page_num`, `text`, `extraction_method`, `bbox_blocks?`

### Salida mínima

* Texto limpio completo: `clean_text.txt`
* Texto limpio por página (auditable): `clean_text_pages.jsonl`
* Reporte de limpieza: `outputs/reports/<doc_id>.json`

---

## 2) Orden recomendado de transformaciones (pipeline de limpieza)

1. **Normalización Unicode y caracteres invisibles**
2. **Normalización de espacios**
3. **Remoción de headers/footers repetidos**
4. **Remoción de números de página**
5. **De-hyphenation (unión de palabras cortadas)**
6. **Unión de líneas dentro de párrafos**
7. **Preservación/normalización de listas y bullets**
8. **Manejo de columnas (si aplica)**
9. **Post-procesos OCR (correcciones conservadoras)**
10. **Re-sentencización (NLP) y validación**

Cada etapa debe poder:

* producir métricas
* registrar ejemplos de cambios (muestreo)

---

## 3) Reglas detalladas

### 3.1 Normalización Unicode y caracteres invisibles

**Objetivo**: evitar caracteres “raros” que rompen tokenización y embeddings.

Reglas:

* Convertir a una forma Unicode consistente (NFC o NFKC según config).
* Reparar mojibake y secuencias mal decodificadas (ftfy).
* Remover caracteres de control excepto `\n` y `\t`.
* Normalizar guiones y comillas (variantes unicode) a formas comunes.

**Métrica sugerida**:

* `unicode_fixes_count`
* `control_chars_removed`

---

### 3.2 Normalización de espacios

**Objetivo**: eliminar artefactos como espacios duplicados, tabs aleatorios y líneas con solo espacios.

Reglas:

* Reemplazar `\t` por espacios (configurable).
* Colapsar múltiples espacios en uno, excepto cuando afecte alineación de tablas (ver 3.7).
* Eliminar trailing spaces por línea.
* Colapsar más de 3 saltos de línea consecutivos a 2 (configurable).

**Métrica**:

* `spaces_collapsed`
* `blank_lines_removed`

---

### 3.3 Remoción de headers/footers repetidos

**Objetivo**: quitar encabezados/pies que se repiten en muchas páginas y contaminan RAG.

**Estrategia recomendada** (sin depender de DL):

1. Para cada página, tomar:

   * primeras `N` líneas (header candidates)
   * últimas `M` líneas (footer candidates)
2. Normalizar estas líneas (lowercase + quitar números variables + colapsar espacios).
3. Contar frecuencia por documento.
4. Si una línea aparece en >= `X%` de páginas, marcarla como header/footer.
5. Eliminarla de todas las páginas.

**Reglas conservadoras**:

* No eliminar si la línea parece un título de sección (ej. “Capítulo 3”) y cambia por página.
* No eliminar si contiene demasiadas palabras únicas (baja repetición real).

**Métricas**:

* `header_lines_removed`
* `footer_lines_removed`
* `header_footer_patterns_detected`

**Ejemplo (antes → después)**

Antes:

* `Manual de Operación — Equipo X`
* `...contenido...`
* `Página 12`

Después:

* `...contenido...`

---

### 3.4 Remoción de números de página

**Objetivo**: eliminar contadores que a veces no fueron detectados como footer.

Patrones típicos:

* `^\s*\d+\s*$`
* `^\s*Página\s*\d+\s*$`
* `^\s*Page\s*\d+\s*$`
* `^\s*\d+\s*/\s*\d+\s*$` (12/120)

**Regla**:

* Si la línea coincide con patrón y está dentro de las últimas `K` líneas → remover.

**Métrica**:

* `page_numbers_removed`

---

### 3.5 De-hyphenation (unión de palabras cortadas)

**Problema**: PDF/OCR produce cortes como:

* `implemen-\n tación`
* `inter-\n nacional`

**Regla principal (conservadora)**
Unir si:

1. La línea termina con `-` (o guion unicode similar).
2. La siguiente línea comienza con letra minúscula.
3. No hay espacio antes del guion (evitar listas tipo `- item`).
4. La unión produce una palabra razonable (heurística):

   * longitud total <= umbral
   * no introduce caracteres raros

**Reglas de no-unión**
No unir si:

* La siguiente línea comienza con mayúscula (posible título o inicio de oración).
* La parte izquierda es muy corta (<=2) o muy larga (>=30) según config.
* La unión cruza signos raros (ej. `)-\n`), probablemente no palabra.

**Métrica**:

* `dehyphen_joins`
* `dehyphen_skips`

**Ejemplos**

Antes:

* `La implemen-`
* `tación del sistema...`

Después:

* `La implementación del sistema...`

Antes:

* `- Ajuste-`
* `miento` (caso ambiguo)

Después:

* *Preferir NO unir* si se detecta lista/bullet.

---

### 3.6 Unión de líneas dentro de párrafos

**Objetivo**: reconstruir párrafos cuando el PDF insertó saltos en cada renglón.

**Heurística de unión (line join decision)**
Dadas dos líneas consecutivas `L1` y `L2`:

Unir con espacio si se cumple todo esto:

* `L1` no termina en un delimitador fuerte:

  * `. ! ? :` (configurable)
* `L1` no parece encabezado (ver 3.8).
* `L2` no parece inicio de nuevo bloque:

  * comienza con bullet (`-`, `•`, `*`)
  * comienza con numeración tipo lista (`1.`, `1)`, `a)`, `I.`)
* `L2` comienza con minúscula, o con una palabra que no indica título.

**No unir (mantener salto de párrafo) si**:

* `L1` termina con punto y `L2` inicia con mayúscula (muy probable nueva oración).
* Hay línea en blanco entre medio (se considera nuevo párrafo).
* `L2` tiene indentación/tabs muy distinta (si la extracción preserva espacios).

**Caso especial: guiones ya resueltos**

* Si 3.5 unió palabras, evitar doble espacio o concatenaciones extrañas.

**Métricas**:

* `line_joins`
* `paragraph_breaks_kept`
* `avg_line_length_before_after`

**Ejemplo**
Antes:

* `Este sistema permite la integración`
* `con módulos externos para...`

Después:

* `Este sistema permite la integración con módulos externos para...`

---

### 3.7 Preservación de listas y bullets

**Objetivo**: no romper listas, porque son muy importantes en manuales.

Detección de bullet/lista:

* `^\s*[-•*]\s+`
* `^\s*\d+[\.)]\s+`
* `^\s*[a-zA-Z][\.)]\s+`
* `^\s*[IVXLCDM]+[\.)]\s+` (romanos)

Reglas:

* Si `L2` es bullet, **no unir** con `L1`.
* Si una lista se extiende en varias líneas (wrapped lines):

  * unir líneas siguientes al bullet mientras mantengan indentación o no inicien con otro bullet.
* Normalizar bullets a un estándar (opcional):

  * convertir `•` a `-` (configurable) para Markdown.

Métricas:

* `bullets_detected`
* `wrapped_bullet_lines_joined`

---

### 3.8 Encabezados de sección y títulos

**Objetivo**: preservar estructura y evitar unir títulos con párrafos.

Heurísticas para detectar títulos:

* Línea corta (<= `T` caracteres) y alta proporción de mayúsculas.
* Patrón numerado: `^\s*(Cap(í|i)tulo|Secci(ó|o)n)\s+\d+`.
* Patrón tipo `1.2.3 Título`.
* No termina en punto.

Reglas:

* Insertar separación antes/después de títulos (doble salto configurable).
* No unir título con la siguiente línea aunque cumpla heurística de minúscula.

Métrica:

* `headings_detected`

---

### 3.9 Manejo de columnas (layout)

**Objetivo**: evitar concatenaciones incorrectas en PDFs multi-columna.

Modo A (sin bounding boxes, básico):

* Detectar si muchas líneas son muy cortas y con patrones alternantes.
* Si se sospecha multi-columna, **no forzar unión agresiva**; usar reglas más conservadoras.

Modo B (con pdfplumber bbox blocks, recomendado):

* Agrupar texto por bloques/zonas (x0/x1):

  * columna izquierda completa (top→bottom)
  * luego columna derecha
* Solo después aplicar 3.5 y 3.6 dentro de cada columna.

Métrica:

* `multicolumn_suspected`
* `blocks_used`

---

### 3.10 Correcciones OCR (conservadoras)

**Objetivo**: corregir errores típicos sin introducir falsos positivos.

Reglas (sugeridas, opcionales):

* Reemplazar ligaduras comunes: `ﬁ`→`fi`, `ﬂ`→`fl`.
* Corregir comillas extrañas.
* Evitar correcciones tipo `O`↔`0` salvo en contextos claros (ej. IDs numéricos).

Métrica:

* `ocr_fixes_count`

---

### 3.11 Re-sentencización y validación (NLP)

**Objetivo**: validar que el texto final tenga oraciones coherentes.

Acciones:

* Sentencización con spaCy.
* Detectar oraciones demasiado largas (posible unión excesiva) y marcarlas.
* Detectar demasiadas oraciones de 1–2 palabras (posible salto excesivo) y marcar.

Métricas:

* `sentences_count`
* `long_sentences_flagged`
* `short_sentences_flagged`

---

## 4) QA: Indicadores de “texto semánticamente sano”

Checks recomendados por documento:

* % páginas con texto vacío (debe ser bajo).
* Promedio de caracteres por página (evitar 0 o extremadamente bajo).
* Ratio `line_joins / total_lines` (si es 0, no se reconstruyó nada; si es altísimo, quizá unió de más).
* Conteo de headings detectados (si es 0 en manuales estructurados, algo falló).
* Tablas extraídas vs páginas con tablas esperadas.

---

## 5) Configuración sugerida (keys)

En `configs/default.yaml`:

* `cleaning.unicode.form = NFC|NFKC`
* `cleaning.header_footer.header_lines = 3`
* `cleaning.header_footer.footer_lines = 3`
* `cleaning.header_footer.min_page_ratio = 0.6`
* `cleaning.dehyphen.max_left = 30`
* `cleaning.dehyphen.min_left = 3`
* `cleaning.line_join.max_blank_lines = 2`
* `cleaning.headings.max_len = 80`
* `cleaning.lists.normalize_bullets = true|false`
* `layout.multicolumn.use_bboxes = true|false`

---

## 6) Ejemplos de antes/después (mini-casos)

### Caso A: saltos por renglón

Antes:

```
El sistema permite la integración
con módulos externos para mejorar
la disponibilidad.
```

Después:

```
El sistema permite la integración con módulos externos para mejorar la disponibilidad.
```

### Caso B: de-hyphen

Antes:

```
La implemen-
 tación del módulo...
```

Después:

```
La implementación del módulo...
```

### Caso C: lista

Antes:

```
Requisitos:
- Conexión estable
  a la red interna
- Permisos de administrador
```

Después:

```
Requisitos:
- Conexión estable a la red interna
- Permisos de administrador
```

---

## 7) Notas de implementación (para el futuro)

* Las reglas 3.5 y 3.6 deben operar sobre una representación de líneas que preserve:

  * texto
  * posición (si está disponible)
  * page_num
* Para trazabilidad, registrar ejemplos de cambios (muestreo) en `reports/<doc_id>.json`:

  * `before`, `after`, `rule`, `page_num`
* Evitar heurísticas “globales” que no respeten el contexto de página/bloque.

---

**Este documento es el contrato de calidad del proyecto.**
Si lo que sale no respeta estas reglas, el RAG se rompe aunque la extracción “funcione”.
