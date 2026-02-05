# src/limpiatextos/stages/clean.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from limpiatextos.core.models import Artifact, ArtifactType, Document
from limpiatextos.pipeline.registry import stage
from limpiatextos.pipeline.stages import StageContext
from limpiatextos.core import logging as metrics


_RAW_PATH = "raw_text_pages.jsonl"
_CLEAN_PAGES_PATH = "clean_text_pages.jsonl"
_CLEAN_TEXT_PATH = "clean_text.txt"


def _load_pages(raw_jsonl: Path) -> List[Dict]:
    pages: List[Dict] = []
    with raw_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            pages.append(json.loads(line))
    return pages


def _normalize_whitespace(text: str) -> str:
    # normaliza CRLF, tabs, múltiples espacios, y limpia trailing spaces por línea
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    text = "\n".join([ln.rstrip() for ln in text.split("\n")])
    # colapsa espacios múltiples (pero deja saltos de línea intactos)
    text = re.sub(r"[ ]{2,}", " ", text)
    return text.strip()


def _dehyphen(text: str) -> Tuple[str, int, List[Tuple[str, str]]]:
    """
    Une separaciones por guión al final de línea:
      'implemen-\\n tación' => 'implementación'
    Devuelve: (nuevo_texto, conteo_joins, samples[(before, after)])
    """
    joins = 0
    samples: List[Tuple[str, str]] = []

    # patrón: letras + '-' + salto + espacios + letras
    pattern = re.compile(r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,})-\n\s*([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,})")

    def _repl(m: re.Match) -> str:
        nonlocal joins, samples
        before = m.group(0)
        after = f"{m.group(1)}{m.group(2)}"
        joins += 1
        if len(samples) < 10:
            samples.append((before, after))
        return after

    new_text = pattern.sub(_repl, text)
    return new_text, joins, samples


def _join_soft_wraps(text: str) -> Tuple[str, int]:
    """
    Une saltos de línea "suaves" dentro de párrafo.
    Heurística:
      - Une '\n' cuando no está precedido por puntuación fuerte
      - y la siguiente línea no parece un bullet/título
    """
    joins = 0
    lines = text.split("\n")
    out: List[str] = []
    i = 0

    bullet_re = re.compile(r"^\s*([•\-\*]|\d+[\.\)]|[A-Za-z]\))\s+")
    heading_like_re = re.compile(r"^\s*[A-ZÁÉÍÓÚÜÑ0-9][A-ZÁÉÍÓÚÜÑ0-9\s\-\–]{3,}\s*$")

    while i < len(lines):
        cur = lines[i].strip()
        if cur == "":
            out.append("")
            i += 1
            continue

        # acumula líneas mientras parezcan parte del mismo párrafo
        buf = cur
        i += 1
        while i < len(lines):
            nxt_raw = lines[i]
            nxt = nxt_raw.strip()

            if nxt == "":
                break  # fin de párrafo

            if bullet_re.match(nxt_raw) or heading_like_re.match(nxt_raw):
                break  # no unir bullets/títulos

            # si la línea actual termina con puntuación fuerte, no unir
            if re.search(r"[\.!\?:;]\s*$", buf):
                break

            # unir
            buf = buf + " " + nxt
            joins += 1
            i += 1

        out.append(buf)
        i += 1 if (i < len(lines) and lines[i].strip() == "") else 0

    return "\n".join(out).strip(), joins


@dataclass
class CleanStage:
    name: str = "clean"
    requires: Sequence[ArtifactType] = ("raw_text_pages",)
    produces: Sequence[ArtifactType] = ("clean_text_pages", "clean_text")
    idempotent: bool = True

    def run(self, doc: Document, ctx: StageContext) -> Document:
        doc.ensure_workspace()

        raw_path = doc.workspace_doc_dir / _RAW_PATH
        if not raw_path.exists() or raw_path.stat().st_size == 0:
            # No fallamos duro: QA/validate lo decidirá
            metrics.emit(doc.doc_id, "clean_input_missing", True, tags={"stage": self.name})
            # igual creamos outputs vacíos para idempotencia
            (doc.workspace_doc_dir / _CLEAN_PAGES_PATH).write_text("", encoding="utf-8")
            (doc.workspace_doc_dir / _CLEAN_TEXT_PATH).write_text("", encoding="utf-8")
            doc.register_artifact(Artifact(type="clean_text_pages", path=_CLEAN_PAGES_PATH, mime="application/x-ndjson"))
            doc.register_artifact(Artifact(type="clean_text", path=_CLEAN_TEXT_PATH, mime="text/plain"))
            metrics.emit(doc.doc_id, "clean_ok", False, tags={"stage": self.name})
            return doc

        pages = _load_pages(raw_path)

        # sampling config
        samples_per_doc = int(((ctx.config.get("reporting") or {}).get("samples_per_doc") or 10))
        sample_budget = max(0, samples_per_doc)

        dehyphen_joins_total = 0
        line_joins_total = 0
        chars_clean_total = 0

        clean_pages_path = doc.workspace_doc_dir / _CLEAN_PAGES_PATH
        clean_text_path = doc.workspace_doc_dir / _CLEAN_TEXT_PATH

        clean_all_pages_text: List[str] = []

        with clean_pages_path.open("w", encoding="utf-8") as fpages:
            for row in pages:
                page_num = int(row.get("page", 0))
                before = str(row.get("text", "") or "")
                t = _normalize_whitespace(before)

                t2, dj, dehy_samples = _dehyphen(t)
                dehyphen_joins_total += dj

                t3, lj = _join_soft_wraps(t2)
                line_joins_total += lj

                after = t3
                chars_clean_total += len(after)
                clean_all_pages_text.append(after)

                fpages.write(json.dumps({"page": page_num, "text": after}, ensure_ascii=False) + "\n")

                # samples: prioriza dehyphen samples reales
                if sample_budget > 0 and dehy_samples:
                    b, a = dehy_samples[0]
                    metrics.add_sample(
                        doc.doc_id,
                        {"page": page_num, "rule": "dehyphen", "before": b, "after": a},
                    )
                    sample_budget -= 1
                elif sample_budget > 0 and before.strip() != after.strip():
                    metrics.add_sample(
                        doc.doc_id,
                        {
                            "page": page_num,
                            "rule": "clean_generic",
                            "before": before[:400],
                            "after": after[:400],
                        },
                    )
                    sample_budget -= 1

        # clean_text.txt concatenado (separador doble salto para no mezclar páginas)
        clean_text_path.write_text("\n\n".join(clean_all_pages_text).strip() + "\n", encoding="utf-8")

        # registrar artifacts
        doc.register_artifact(
            Artifact(
                type="clean_text_pages",
                path=_CLEAN_PAGES_PATH,
                mime="application/x-ndjson",
                meta={"producer": "clean", "ruleset": "v1"},
            )
        )
        doc.register_artifact(
            Artifact(
                type="clean_text",
                path=_CLEAN_TEXT_PATH,
                mime="text/plain",
                meta={"producer": "clean", "ruleset": "v1"},
            )
        )

        # métricas
        metrics.emit(doc.doc_id, "dehyphen_joins", dehyphen_joins_total, tags={"stage": self.name})
        metrics.emit(doc.doc_id, "line_joins", line_joins_total, tags={"stage": self.name})
        metrics.emit(doc.doc_id, "chars_clean_total", chars_clean_total, tags={"stage": self.name})
        metrics.emit(doc.doc_id, "clean_ok", True, tags={"stage": self.name})

        metrics.set_meta(doc.doc_id, "dehyphen_joins", dehyphen_joins_total)
        metrics.set_meta(doc.doc_id, "line_joins", line_joins_total)
        metrics.set_meta(doc.doc_id, "chars_clean_total", chars_clean_total)

        return doc


@stage("clean", order=70)
def make_clean() -> CleanStage:
    return CleanStage()
