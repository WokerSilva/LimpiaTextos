# src/limpiatextos/stages/diagnose.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.limpiatextos.core.models import Artifact, ArtifactType, Document, Page
from src.limpiatextos.pipeline.registry import stage
from src.limpiatextos.pipeline.stages import StageContext
from src.limpiatextos.core import logging as metrics


def _try_extract_text_per_page_pypdf(pdf_path: Path) -> Tuple[int, Optional[List[str]]]:
    """
    Devuelve (pages_total, texts_per_page or None).
    texts_per_page=None si pypdf no está disponible o extracción falló.
    """
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return 0, None

    try:
        reader = PdfReader(str(pdf_path))
        pages_total = len(reader.pages)
        texts: List[str] = []
        for p in reader.pages:
            t = p.extract_text() or ""
            texts.append(t)
        return pages_total, texts
    except Exception:
        return 0, None


@dataclass
class DiagnoseStage:
    name: str = "diagnose"
    requires: Sequence[ArtifactType] = ("manifest", "plan")
    produces: Sequence[ArtifactType] = ("raw_text_pages",)
    idempotent: bool = True

    def run(self, doc: Document, ctx: StageContext) -> Document:
        doc.ensure_workspace()
        pdf_path = Path(doc.source_path)

        pages_total, texts = _try_extract_text_per_page_pypdf(pdf_path)

        # Si no pudimos leer páginas, dejamos pages_total como None/0, pero NO fallamos el pipeline.
        if pages_total <= 0:
            metrics.emit(doc.doc_id, "diagnose_pages_total_unknown", True, tags={"stage": self.name})
            doc.meta["pages_total"] = 0
            metrics.set_meta(doc.doc_id, "pages_total", 0)
            return doc

        doc.meta["pages_total"] = pages_total
        metrics.set_meta(doc.doc_id, "pages_total", pages_total)

        pages: List[Page] = []
        pages_with_text = 0
        char_counts: List[int] = []

        if texts is None:
            # No tenemos texto por página; solo medimos páginas
            for i in range(pages_total):
                pages.append(Page(page_num=i + 1, char_count=0, has_text=False))
            doc.pages = pages
            metrics.emit(doc.doc_id, "diagnose_text_extraction_available", False, tags={"stage": self.name})
            return doc

        # Sí tenemos textos por página
        raw_jsonl_path = doc.workspace_doc_dir / "raw_text_pages.jsonl"
        with raw_jsonl_path.open("w", encoding="utf-8") as f:
            for i, t in enumerate(texts, start=1):
                t_norm = t.strip()
                c = len(t_norm)
                has_text = c > 0
                pages_with_text += 1 if has_text else 0
                char_counts.append(c)

                pages.append(Page(page_num=i, char_count=c, has_text=has_text))
                f.write(json.dumps({"page": i, "text": t_norm}, ensure_ascii=False) + "\n")

        doc.pages = pages

        pages_empty = pages_total - pages_with_text
        pages_empty_ratio = (pages_empty / pages_total) if pages_total else 1.0
        chars_mean = (sum(char_counts) / len(char_counts)) if char_counts else 0.0

        # Emit metrics base (alineadas con QA thresholds)
        metrics.emit(doc.doc_id, "pages_with_text_count", pages_with_text, tags={"stage": self.name})
        metrics.emit(doc.doc_id, "pages_empty_count", pages_empty, tags={"stage": self.name})
        metrics.emit(doc.doc_id, "pages_empty_ratio", pages_empty_ratio, tags={"stage": self.name})
        metrics.emit(doc.doc_id, "chars_per_page_mean", chars_mean, tags={"stage": self.name})

        metrics.set_meta(doc.doc_id, "pages_with_text_count", pages_with_text)
        metrics.set_meta(doc.doc_id, "pages_empty_ratio", pages_empty_ratio)
        metrics.set_meta(doc.doc_id, "chars_per_page_mean", chars_mean)

        # Registrar artifact diagnóstico
        doc.register_artifact(
            Artifact(
                type="raw_text_pages",
                path="raw_text_pages.jsonl",
                mime="application/x-ndjson",
                meta={"producer": "diagnose", "method": "pypdf.extract_text"},
            )
        )

        metrics.emit(doc.doc_id, "diagnose_ok", True, tags={"stage": self.name})
        return doc


@stage("diagnose", order=20)
def make_diagnose() -> DiagnoseStage:
    return DiagnoseStage()
