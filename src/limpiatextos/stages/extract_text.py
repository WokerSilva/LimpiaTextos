# src/limpiatextos/stages/extract_text.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from limpiatextos.core.models import Artifact, ArtifactType, Document
from limpiatextos.pipeline.registry import stage
from limpiatextos.pipeline.stages import StageContext
from limpiatextos.core import logging as metrics


def _try_extract_text_per_page_pypdf(pdf_path: Path) -> Tuple[int, Optional[List[str]]]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return 0, None

    try:
        reader = PdfReader(str(pdf_path))
        pages_total = len(reader.pages)
        texts: List[str] = []
        for p in reader.pages:
            texts.append((p.extract_text() or ""))
        return pages_total, texts
    except Exception:
        return 0, None


def _raw_pages_path(doc: Document) -> Path:
    return doc.workspace_doc_dir / "raw_text_pages.jsonl"


@dataclass
class ExtractTextStage:
    name: str = "extract_text"
    requires: Sequence[ArtifactType] = ("manifest", "plan")
    produces: Sequence[ArtifactType] = ("raw_text_pages",)
    idempotent: bool = True

    def run(self, doc: Document, ctx: StageContext) -> Document:
        doc.ensure_workspace()

        raw_path = _raw_pages_path(doc)

        # 1) Reusar si ya existe (diagnose u otro)
        if raw_path.exists() and raw_path.stat().st_size > 0:
            metrics.emit(doc.doc_id, "extract_text_reused_raw_pages", True, tags={"stage": self.name})
            doc.register_artifact(
                Artifact(
                    type="raw_text_pages",
                    path="raw_text_pages.jsonl",
                    mime="application/x-ndjson",
                    meta={"producer": "extract_text", "method": "reuse"},
                )
            )
            # Señales OCR (por ahora: no usado en esta etapa)
            metrics.set_meta(doc.doc_id, "ocr_used", False)
            metrics.emit(doc.doc_id, "ocr_used", False, tags={"stage": self.name})
            return doc

        # 2) Extraer con pypdf
        pdf_path = Path(doc.source_path)
        pages_total, texts = _try_extract_text_per_page_pypdf(pdf_path)

        if pages_total <= 0 or texts is None:
            # 3) No se pudo extraer
            raw_path.write_text("", encoding="utf-8")
            doc.register_artifact(
                Artifact(
                    type="raw_text_pages",
                    path="raw_text_pages.jsonl",
                    mime="application/x-ndjson",
                    meta={"producer": "extract_text", "method": "unavailable"},
                )
            )
            metrics.emit(doc.doc_id, "extract_text_ok", False, tags={"stage": self.name})
            metrics.emit(doc.doc_id, "extract_text_pages_total_unknown", True, tags={"stage": self.name})
            metrics.set_meta(doc.doc_id, "ocr_used", False)
            metrics.emit(doc.doc_id, "ocr_used", False, tags={"stage": self.name})
            return doc

        # Escribir jsonl por página
        with raw_path.open("w", encoding="utf-8") as f:
            pages_with_text = 0
            char_counts = []

            for i, t in enumerate(texts, start=1):
                t_norm = (t or "").strip()
                c = len(t_norm)
                if c > 0:
                    pages_with_text += 1
                char_counts.append(c)
                f.write(json.dumps({"page": i, "text": t_norm}, ensure_ascii=False) + "\n")

        pages_empty = pages_total - pages_with_text
        pages_empty_ratio = (pages_empty / pages_total) if pages_total else 1.0
        chars_mean = (sum(char_counts) / len(char_counts)) if char_counts else 0.0

        # meta + métricas base
        doc.meta["pages_total"] = pages_total
        metrics.set_meta(doc.doc_id, "pages_total", pages_total)
        metrics.set_meta(doc.doc_id, "pages_with_text_count", pages_with_text)
        metrics.set_meta(doc.doc_id, "pages_empty_ratio", pages_empty_ratio)
        metrics.set_meta(doc.doc_id, "chars_per_page_mean", chars_mean)

        metrics.emit(doc.doc_id, "pages_with_text_count", pages_with_text, tags={"stage": self.name})
        metrics.emit(doc.doc_id, "pages_empty_ratio", pages_empty_ratio, tags={"stage": self.name})
        metrics.emit(doc.doc_id, "chars_per_page_mean", chars_mean, tags={"stage": self.name})

        doc.register_artifact(
            Artifact(
                type="raw_text_pages",
                path="raw_text_pages.jsonl",
                mime="application/x-ndjson",
                meta={"producer": "extract_text", "method": "pypdf.extract_text"},
            )
        )

        # Señales OCR (por ahora: no usado en esta etapa)
        metrics.set_meta(doc.doc_id, "ocr_used", False)
        metrics.emit(doc.doc_id, "ocr_used", False, tags={"stage": self.name})
        metrics.emit(doc.doc_id, "extract_text_ok", True, tags={"stage": self.name})
        return doc


@stage("extract_text", order=40)
def make_extract_text() -> ExtractTextStage:
    return ExtractTextStage()
