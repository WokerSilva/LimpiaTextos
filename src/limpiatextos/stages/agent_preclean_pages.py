from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Optional, Sequence, Tuple

from limpiatextos.core.models import Artifact, ArtifactType, Document
from limpiatextos.pipeline.registry import stage
from limpiatextos.pipeline.stages import StageContext
from limpiatextos.core import logging as metrics


def _raw_pages_path(doc: Document) -> Path:
    return doc.workspace_doc_dir / "raw_text_pages.jsonl"


def _agent_dir(doc: Document) -> Path:
    return doc.workspace_doc_dir / "agent"


def _clean_pages_path(doc: Document) -> Path:
    return _agent_dir(doc) / "pages_clean.jsonl"


def _agent_meta_path(doc: Document) -> Path:
    return _agent_dir(doc) / "meta.json"


# Footer típico: CÓDIGO: ... FECHA: ... VERSIÓN: ... INTERNO PÁGINA X
FOOTER_RE = re.compile(
    r"""^CÓDIGO:\s*(?P<doc_code>[\w\.\-]+)\s+
        FECHA:\s*(?P<raw_date>[\w\/\-\.\s]+?)\s+
        VERSIÓN:\s*(?P<version>[\w\.\-]+)\s+
        (?P<classification>INTERNO|EXTERNO|CONFIDENCIAL)?\s*
        PÁGINA\b.*$""",
    re.IGNORECASE | re.VERBOSE,
)

# Encabezado “basura” típico (aparece solo en una línea)
SPURIOUS_HEADER_RE = re.compile(r"^\s*Control\s+Interno\s*$", re.IGNORECASE)

# Página suelta tipo: "PÁGINA 3" (a veces OCR mete esto dentro)
PAGE_NUM_RE = re.compile(r"^\s*PÁGINA\s+\d+(\s+de\s+\d+)?\s*$", re.IGNORECASE)


def _normalize_text(text: str) -> str:
    # bullets unicode → "-"
    text = text.replace("•", "- ").replace("–", "- ").replace("—", "- ")

    # elimina NULLs y espacios raros
    text = text.replace("\x00", "")

    # arreglar hifenación de fin de línea: "docu-\nmento" → "documento"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    # unir saltos de línea rotos en medio de palabra: "co nstatan" es más complejo;
    # aquí solo colapsamos múltiples espacios (sin “inventar” palabras)
    text = re.sub(r"[ \t]+", " ", text)

    # normalizar saltos de línea múltiples
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _split_lines(text: str) -> List[str]:
    return [ln.strip() for ln in (text or "").splitlines()]


def _remove_footer_and_headers(
    lines: List[str],
    footer_re: re.Pattern,
    meta: Dict[str, Any],
) -> Tuple[List[str], int, int]:
    """
    Devuelve:
    - líneas limpias
    - cantidad de líneas footer removidas
    - cantidad de líneas header/pagenum removidas
    """
    out: List[str] = []
    removed_footer = 0
    removed_headers = 0

    for ln in lines:
        if not ln:
            continue

        # remover page numbers
        if PAGE_NUM_RE.match(ln):
            removed_headers += 1
            continue

        # remover headers sueltos
        if SPURIOUS_HEADER_RE.match(ln):
            removed_headers += 1
            continue

        m = footer_re.match(ln)
        if m:
            removed_footer += 1
            # capturar una vez
            if not meta.get("footer_detected"):
                meta["footer_detected"] = True
                gd = {k: (v.strip() if isinstance(v, str) else v) for k, v in m.groupdict().items()}
                # normaliza a llaves estándar
                if gd.get("doc_code"):
                    meta["doc_code"] = gd["doc_code"]
                if gd.get("raw_date"):
                    meta["raw_date"] = gd["raw_date"]
                if gd.get("version"):
                    meta["version"] = gd["version"]
                if gd.get("classification"):
                    meta["classification"] = gd["classification"].upper()
            continue

        out.append(ln)

    return out, removed_footer, removed_headers


@dataclass
class AgentPrecleanPagesStage:
    name: str = "agent_preclean_pages"
    requires: Sequence[ArtifactType] = ("raw_text_pages",)
    produces: Sequence[ArtifactType] = ("agent_pages_clean", "agent_meta")
    idempotent: bool = True

    def run(self, doc: Document, ctx: StageContext) -> Document:
        doc.ensure_workspace()

        raw_path = _raw_pages_path(doc)
        if not raw_path.exists() or raw_path.stat().st_size == 0:
            raise FileNotFoundError(f"No existe raw_text_pages.jsonl: {raw_path}")

        agent_dir = _agent_dir(doc)
        agent_dir.mkdir(parents=True, exist_ok=True)

        clean_path = _clean_pages_path(doc)
        meta_path = _agent_meta_path(doc)

        # Reusar si ya existe
        if clean_path.exists() and clean_path.stat().st_size > 0 and meta_path.exists():
            metrics.emit(doc.doc_id, "agent_preclean_reused", True, tags={"stage": self.name})
            doc.register_artifact(
                Artifact(
                    type="agent_pages_clean",
                    path=str(clean_path.relative_to(doc.workspace_doc_dir)),
                    mime="application/x-ndjson",
                    meta={"producer": self.name, "method": "reuse"},
                )
            )
            doc.register_artifact(
                Artifact(
                    type="agent_meta",
                    path=str(meta_path.relative_to(doc.workspace_doc_dir)),
                    mime="application/json",
                    meta={"producer": self.name, "method": "reuse"},
                )
            )
            return doc

        meta: Dict[str, Any] = {
            "doc_id": doc.doc_id,
            "source_pdf": Path(doc.source_path).name,
            "footer_detected": False,
        }

        total_pages = 0
        total_footer_removed = 0
        total_headers_removed = 0

        with raw_path.open("r", encoding="utf-8") as fin, clean_path.open("w", encoding="utf-8") as fout:
            for line in fin:
                if not line.strip():
                    continue
                obj = json.loads(line)
                page_num = int(obj.get("page", 0))
                text = (obj.get("text") or "")

                total_pages += 1

                norm = _normalize_text(text)
                lines = _split_lines(norm)

                cleaned_lines, rf, rh = _remove_footer_and_headers(lines, FOOTER_RE, meta)
                total_footer_removed += rf
                total_headers_removed += rh

                cleaned_text = "\n".join(cleaned_lines).strip()

                fout.write(
                    json.dumps({"page": page_num, "text": cleaned_text}, ensure_ascii=False) + "\n"
                )

        # Persist meta
        meta["pages_total"] = total_pages
        meta["footer_lines_removed"] = total_footer_removed
        meta["headers_lines_removed"] = total_headers_removed

        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        # métricas
        metrics.set_meta(doc.doc_id, "agent_footer_detected", bool(meta.get("footer_detected")))
        metrics.set_meta(doc.doc_id, "agent_doc_code", meta.get("doc_code"))
        metrics.set_meta(doc.doc_id, "agent_version", meta.get("version"))
        metrics.set_meta(doc.doc_id, "agent_raw_date", meta.get("raw_date"))
        metrics.set_meta(doc.doc_id, "agent_classification", meta.get("classification"))
        metrics.emit(doc.doc_id, "agent_footer_lines_removed", total_footer_removed, tags={"stage": self.name})
        metrics.emit(doc.doc_id, "agent_headers_lines_removed", total_headers_removed, tags={"stage": self.name})

        # registrar artefactos
        doc.register_artifact(
            Artifact(
                type="agent_pages_clean",
                path=str(clean_path.relative_to(doc.workspace_doc_dir)),
                mime="application/x-ndjson",
                meta={"producer": self.name, "method": "regex_clean"},
            )
        )
        doc.register_artifact(
            Artifact(
                type="agent_meta",
                path=str(meta_path.relative_to(doc.workspace_doc_dir)),
                mime="application/json",
                meta={"producer": self.name, "method": "regex_clean"},
            )
        )

        return doc


@stage("agent_preclean_pages", order=60)
def make_agent_preclean_pages() -> AgentPrecleanPagesStage:
    return AgentPrecleanPagesStage()
