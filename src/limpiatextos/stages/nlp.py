# src/limpiatextos/stages/nlp.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.limpiatextos.core.models import Artifact, ArtifactType, Document
from src.limpiatextos.pipeline.registry import stage
from src.limpiatextos.pipeline.stages import StageContext
from src.limpiatextos.core import logging as metrics


_HEADING_NUM_RE = re.compile(r"^\s*(\d+(\.\d+){0,5})[\)\.]?\s+(.+?)\s*$")
_ALLCAPS_RE = re.compile(r"^[A-ZÁÉÍÓÚÜÑ0-9][A-ZÁÉÍÓÚÜÑ0-9\s\-\–,:;/]{6,}$")
_BULLET_RE = re.compile(r"^\s*([•\-\*]|\d+[\.\)]|[A-Za-z]\))\s+")
_KEYVAL_RE = re.compile(r"^\s*([A-Za-zÁÉÍÓÚÜÑáéíóúüñ][\w\s\-/]{1,40}?)\s*:\s*(.+?)\s*$")


def _load_clean_pages(path: Path) -> List[Dict[str, Any]]:
    pages: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            pages.append(json.loads(ln))
    return pages


def _split_lines_keep(text: str) -> List[str]:
    # Mantiene líneas para detectar headings/listas/tablas
    return [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]


def _heading_level_from_number(num: str) -> int:
    # "1"->2, "1.1"->3, "1.1.1"->4 ... (cap a 6)
    depth = num.count(".") + 1
    return min(2 + depth - 1, 6)


def _is_probable_heading(line: str) -> Optional[Tuple[int, str]]:
    s = line.strip()
    if not s:
        return None

    m = _HEADING_NUM_RE.match(s)
    if m:
        level = _heading_level_from_number(m.group(1))
        title = m.group(3).strip()
        # evita headings demasiado largos
        if 3 <= len(title) <= 140:
            return level, title

    # all caps => heading (nivel 2)
    if _ALLCAPS_RE.match(s) and len(s) <= 120:
        return 2, s.title()  # title-case para legibilidad

    # "X:" tipo encabezado corto (nivel 3)
    if s.endswith(":") and 3 <= len(s) <= 80 and not _BULLET_RE.match(s):
        return 3, s[:-1].strip()

    return None


def _detect_table_block(lines: List[str], i: int) -> Optional[Tuple[int, List[List[str]]]]:
    """
    Heurística de tabla:
    - 3+ líneas seguidas
    - cada línea tiene 2+ columnas separadas por 2+ espacios
    - mismo número de columnas en el bloque
    Retorna: (end_index_exclusive, rows_as_cells)
    """
    def split_cols(ln: str) -> List[str]:
        cols = [c.strip() for c in re.split(r"\s{2,}", ln.strip()) if c.strip()]
        return cols

    rows: List[List[str]] = []
    j = i
    while j < len(lines):
        ln = lines[j]
        if not ln.strip():
            break
        if _BULLET_RE.match(ln.strip()):
            break
        cols = split_cols(ln)
        if len(cols) < 2:
            break
        rows.append(cols)
        j += 1

    if len(rows) < 3:
        return None

    col_count = len(rows[0])
    if col_count < 2:
        return None
    if any(len(r) != col_count for r in rows):
        return None

    return j, rows


def _render_table_md(rows: List[List[str]]) -> str:
    # Primera fila como header
    header = rows[0]
    body = rows[1:]
    md = []
    md.append("| " + " | ".join(header) + " |")
    md.append("| " + " | ".join(["---"] * len(header)) + " |")
    for r in body:
        md.append("| " + " | ".join(r) + " |")
    return "\n".join(md)


def _format_line_md(line: str) -> str:
    s = line.rstrip()

    # Listas: se pasan tal cual (normaliza bullets a "- ")
    if _BULLET_RE.match(s):
        s2 = _BULLET_RE.sub("- ", s, count=1)
        return s2

    # Key: Value => **Key:** Value
    m = _KEYVAL_RE.match(s)
    if m:
        key = m.group(1).strip()
        val = m.group(2).strip()
        if 1 <= len(key) <= 40 and val:
            return f"**{key}:** {val}"

    return s


def _new_section(title: str, level: int, page_start: int) -> Dict[str, Any]:
    return {
        "title": title,
        "level": level,           # 1..6 (md headings)
        "page_start": page_start,
        "page_end": page_start,
        "content_md": [],
        "children": [],
    }


def _append_to_section(sec: Dict[str, Any], md_line: str, page_num: int) -> None:
    if md_line is None:
        return
    sec["content_md"].append(md_line)
    sec["page_end"] = max(sec.get("page_end", page_num), page_num)


def _insert_section(tree: Dict[str, Any], sec: Dict[str, Any], stack: List[Dict[str, Any]]) -> None:
    """
    Inserta sec en jerarquía usando stack por niveles.
    stack contiene secciones abiertas (monótono por nivel).
    """
    level = sec["level"]

    # Pop hasta encontrar padre con nivel menor
    while stack and stack[-1]["level"] >= level:
        stack.pop()

    if not stack:
        tree["children"].append(sec)
    else:
        stack[-1]["children"].append(sec)

    stack.append(sec)


@dataclass
class NLPStage:
    name: str = "nlp"
    requires: Sequence[ArtifactType] = ("clean_text_pages",)
    produces: Sequence[ArtifactType] = ("sections",)
    idempotent: bool = True

    def run(self, doc: Document, ctx: StageContext) -> Document:
        doc.ensure_workspace()

        clean_pages_path = doc.workspace_doc_dir / "clean_text_pages.jsonl"
        if not clean_pages_path.exists() or clean_pages_path.stat().st_size == 0:
            metrics.emit(doc.doc_id, "nlp_input_missing", True, tags={"stage": self.name})
            out = {"doc_id": doc.doc_id, "title": doc.meta.get("source_filename", doc.doc_id), "children": []}
            (doc.workspace_doc_dir / "sections.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            doc.register_artifact(Artifact(type="sections", path="sections.json", mime="application/json"))
            metrics.emit(doc.doc_id, "nlp_ok", False, tags={"stage": self.name})
            return doc

        pages = _load_clean_pages(clean_pages_path)

        title = doc.meta.get("source_filename", doc.doc_id)
        tree: Dict[str, Any] = {"doc_id": doc.doc_id, "title": title, "children": []}
        stack: List[Dict[str, Any]] = []

        # sección “default” si no hay headings detectados
        current = _new_section(title="Contenido", level=2, page_start=1)
        _insert_section(tree, current, stack)

        headings_found = 0
        table_blocks = 0

        for row in pages:
            page_num = int(row.get("page", 0) or 0)
            text = str(row.get("text", "") or "")
            lines = _split_lines_keep(text)

            i = 0
            while i < len(lines):
                ln = lines[i]
                s = ln.strip()

                if not s:
                    _append_to_section(current, "", page_num)
                    i += 1
                    continue

                # tabla
                tb = _detect_table_block(lines, i)
                if tb:
                    end_i, rows_cells = tb
                    md_table = _render_table_md(rows_cells)
                    _append_to_section(current, md_table, page_num)
                    table_blocks += 1
                    i = end_i
                    continue

                # heading
                h = _is_probable_heading(ln)
                if h:
                    level, htitle = h
                    headings_found += 1
                    sec = _new_section(title=htitle, level=level, page_start=page_num)
                    # inserta en árbol con stack por nivel
                    # stack actual está en tree; tomamos stack “real” reconstruyéndolo desde tree->stack no es necesario
                    # reutilizamos stack de secciones ya insertadas (current es stack[-1])
                    _insert_section(tree, sec, stack)
                    current = sec
                    i += 1
                    continue

                # normal line/list/keyval
                _append_to_section(current, _format_line_md(ln), page_num)
                i += 1

        payload = {
            "doc_id": doc.doc_id,
            "title": title,
            "children": tree["children"],
            "stats": {
                "headings_found": headings_found,
                "table_blocks_detected": table_blocks,
            },
        }

        out_path = doc.workspace_doc_dir / "sections.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        doc.register_artifact(
            Artifact(
                type="sections",
                path="sections.json",
                mime="application/json",
                meta={"producer": "nlp", "method": "heuristics"},
            )
        )

        metrics.emit(doc.doc_id, "headings_found", headings_found, tags={"stage": self.name})
        metrics.emit(doc.doc_id, "table_blocks_detected", table_blocks, tags={"stage": self.name})
        metrics.emit(doc.doc_id, "nlp_ok", True, tags={"stage": self.name})
        return doc


@stage("nlp", order=80)
def make_nlp() -> NLPStage:
    return NLPStage()
