from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple

from limpiatextos.core.models import Artifact, ArtifactType, Document
from limpiatextos.pipeline.registry import stage
from limpiatextos.pipeline.stages import StageContext
from limpiatextos.core import logging as metrics


# -------------------------
# Paths
# -------------------------

def _agent_dir(doc: Document) -> Path:
    return doc.workspace_doc_dir / "agent"


def _raw_pages_path(doc: Document) -> Path:
    # viene de extract_text.py
    return doc.workspace_doc_dir / "raw_text_pages.jsonl"


def _pages_clean_path(doc: Document) -> Path:
    return _agent_dir(doc) / "pages_clean.jsonl"


# -------------------------
# Regex / heurísticas
# -------------------------

# Secciones típicas que suelen introducir tablas en tu plantilla
TABLE_ANCHOR_RE = re.compile(
    r"^(Bitácora de cambios(?: y mejoras)?|Responsabilidades|Indicadores|Riesgos y controles|Activos de información)\b",
    re.IGNORECASE,
)

# Si aparece una sección numerada, es un corte duro
NEXT_SECTION_RE = re.compile(r"^\s*\d+(\.\d+)*\.\s+\S+")

# Bullets / listas
LIST_RE = re.compile(r"^\s*(?:[-•–]|\d+\.|\d+\)|[A-Z]\)|[IVXLC]+\.)\s+")

# “Heading” no numerado (títulos cortos típicos); lo hacemos conservador
TITLEISH_RE = re.compile(r"^[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ0-9 \-–]{2,70}$")

# Guion de corte al final de línea: "implanta-\nción"
HYPHEN_EOF_RE = re.compile(r"(\w+)-$")

# Abreviaturas que terminan en punto pero NO son fin de frase
ABBREV_RE = re.compile(r"\b(?:No|Núm|Num|Art|Sr|Sra|Dr|Dra|etc)\.$", re.IGNORECASE)

# Conectores típicos (si la siguiente línea inicia con esto, casi seguro es soft-wrap)
CONNECTOR_RE = re.compile(
    r"^(y|e|o|u|de|del|la|el|los|las|en|para|que|con|sin|por|al|a|un|una)\b",
    re.IGNORECASE,
)

# Si termina con puntuación fuerte, NO unir (corte semántico)
HARD_END_RE = re.compile(r"[.?!;:]$|[\)\]»”]$|…$")


def _classify_line(line: str) -> str:
    """
    Retorna: in_table_anchor, in_list, is_heading, body
    """
    s = (line or "").strip()
    if not s:
        return "empty"
    if TABLE_ANCHOR_RE.match(s):
        return "in_table_anchor"
    if LIST_RE.match(s):
        return "in_list"
    if NEXT_SECTION_RE.match(s):
        return "is_heading"
    if TITLEISH_RE.match(s):
        return "is_heading"
    return "body"


def _should_join(prev_line: str, next_line: str) -> bool:
    a = (prev_line or "").rstrip()
    b = (next_line or "").lstrip()
    if not a or not b:
        return False

    # si la siguiente línea parece heading o lista, no unir
    b_kind = _classify_line(b)
    if b_kind in ("in_list", "is_heading", "in_table_anchor"):
        return False

    # si la anterior termina en corte duro, no unir (salvo abreviaturas)
    if HARD_END_RE.search(a) and not ABBREV_RE.search(a.strip()):
        return False

    # si la anterior termina en ":" y lo siguiente es lista, no unir
    if a.rstrip().endswith(":") and LIST_RE.match(b):
        return False

    # si la siguiente empieza con conector o minúscula, buen candidato
    if b and (b[0].islower() or CONNECTOR_RE.match(b)):
        return True

    # fallback: unir si parece soft-wrap (línea previa “no cerró” frase)
    # y la siguiente no arranca como heading/lista
    return True


def _normalize_paragraph_lines(lines: List[str], preserve_breaks: bool) -> List[str]:
    """
    Une soft breaks en párrafos si preserve_breaks=False.
    Si preserve_breaks=True (zona tabla candidata / listas), solo arregla hyphenation.
    """
    out: List[str] = []
    i = 0

    while i < len(lines):
        cur = lines[i].rstrip()
        if not cur.strip():
            out.append("")
            i += 1
            continue

        # arreglar hyphenation: palabra- + siguiente => palabraSiguiente
        if HYPHEN_EOF_RE.search(cur) and i + 1 < len(lines):
            nxt = lines[i + 1].lstrip()
            # une sin espacio y quita guion final
            cur = HYPHEN_EOF_RE.sub(r"\1", cur) + nxt
            i += 2
            out.append(re.sub(r"\s+", " ", cur).strip())
            continue

        if preserve_breaks:
            # en tablas/listas: no “aplastar” estructura
            out.append(re.sub(r"\s+", " ", cur).strip())
            i += 1
            continue

        # joiner de soft-break
        buf = cur
        while i + 1 < len(lines):
            nxt = lines[i + 1]
            if not nxt.strip():
                break
            if not _should_join(buf, nxt):
                break
            buf = (buf.rstrip() + " " + nxt.lstrip()).strip()
            i += 1

        out.append(re.sub(r"\s+", " ", buf).strip())
        i += 1

    # limpia dobles vacíos
    cleaned: List[str] = []
    for ln in out:
        if ln == "" and cleaned and cleaned[-1] == "":
            continue
        cleaned.append(ln)
    return cleaned


@dataclass
class AgentPagesCleanStage:
    name: str = "agent_pages_clean"
    requires: Sequence[ArtifactType] = ("raw_text_pages",)
    produces: Sequence[ArtifactType] = ("agent_pages_clean",)
    idempotent: bool = True

    def run(self, doc: Document, ctx: StageContext) -> Document:
        doc.ensure_workspace()
        _agent_dir(doc).mkdir(parents=True, exist_ok=True)

        raw_path = _raw_pages_path(doc)
        out_path = _pages_clean_path(doc)

        if not raw_path.exists():
            raise FileNotFoundError(f"No existe raw_text_pages.jsonl: {raw_path}")

        # Reusar si existe
        if out_path.exists() and out_path.stat().st_size > 0:
            metrics.emit(doc.doc_id, "agent_pages_clean_reused", True, tags={"stage": self.name})
            doc.register_artifact(
                Artifact(
                    type="agent_pages_clean",
                    path=str(out_path.relative_to(doc.workspace_doc_dir)),
                    mime="application/x-ndjson",
                    meta={"producer": self.name, "method": "reuse"},
                )
            )
            return doc

        joins_applied = 0
        total_breaks = 0

        with raw_path.open("r", encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
            for line in fin:
                obj = json.loads(line)
                page = int(obj.get("page", 0))
                text = (obj.get("text") or "")

                raw_lines = [ln.rstrip("\n") for ln in text.splitlines()]
                # si no hay saltos, nada que hacer
                if len(raw_lines) <= 1:
                    fout.write(json.dumps({"page": page, "text": text.strip()}, ensure_ascii=False) + "\n")
                    continue

                # segmenta por bloques en base a “anclas” y headings/listas
                normalized: List[str] = []
                in_table_zone = False

                i = 0
                while i < len(raw_lines):
                    ln = raw_lines[i]
                    kind = _classify_line(ln)

                    # activar/desactivar zona tabla candidata
                    if kind == "in_table_anchor":
                        in_table_zone = True
                        normalized.append(ln.strip())
                        i += 1
                        continue
                    if in_table_zone and kind == "is_heading":
                        in_table_zone = False
                        # no “comer” la línea, se procesa normal abajo
                        continue

                    # agrupar mini-bloques consecutivos hasta que cambie el contexto
                    block: List[str] = []
                    block_kind = kind

                    while i < len(raw_lines):
                        ln2 = raw_lines[i]
                        k2 = _classify_line(ln2)

                        # cortes de bloque
                        if ln2.strip() == "":
                            block.append("")
                            i += 1
                            break

                        # si cambia a heading/lista/ancla tabla, terminamos bloque
                        if k2 in ("in_table_anchor", "is_heading", "in_list") and block:
                            break

                        block.append(ln2)
                        i += 1

                    preserve = in_table_zone or (block_kind in ("in_list", "is_heading"))
                    before_breaks = sum(1 for _ in range(len(block) - 1) if block[_ + 1].strip())
                    total_breaks += max(0, before_breaks)

                    out_block = _normalize_paragraph_lines(block, preserve_breaks=preserve)

                    # estimación de joins: si reduce número de líneas no vacías
                    in_count = sum(1 for x in block if x.strip())
                    out_count = sum(1 for x in out_block if x.strip())
                    if not preserve and out_count < in_count:
                        joins_applied += (in_count - out_count)

                    normalized.extend(out_block)

                final_text = "\n".join([ln for ln in normalized if ln is not None]).strip()
                fout.write(json.dumps({"page": page, "text": final_text}, ensure_ascii=False) + "\n")

        join_ratio = (joins_applied / total_breaks) if total_breaks else 0.0
        metrics.set_meta(doc.doc_id, "softwrap_joins_applied", joins_applied)
        metrics.set_meta(doc.doc_id, "softwrap_total_breaks", total_breaks)
        metrics.set_meta(doc.doc_id, "softwrap_join_ratio", join_ratio)

        metrics.emit(doc.doc_id, "softwrap_joins_applied", joins_applied, tags={"stage": self.name})
        metrics.emit(doc.doc_id, "softwrap_join_ratio", join_ratio, tags={"stage": self.name})

        doc.register_artifact(
            Artifact(
                type="agent_pages_clean",
                path=str(out_path.relative_to(doc.workspace_doc_dir)),
                mime="application/x-ndjson",
                meta={"producer": self.name, "method": "softwrap_joiner_v1"},
            )
        )
        return doc


@stage("agent_pages_clean", order=70)
def make_agent_pages_clean() -> AgentPagesCleanStage:
    return AgentPagesCleanStage()
