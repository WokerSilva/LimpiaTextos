# src/limpiatextos/stages/extract_pages_text.py
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Dict, Any

from pypdf import PdfReader

from limpiatextos.pipeline.registry import stage
from limpiatextos.core.models import Document


@stage(name="extract_pages_text", order=110)
class ExtractPagesText:
    """
    Extrae texto por página y lo guarda como JSON.
    Este artefacto es la base para:
    - detectar y remover pie de página
    - detectar índice
    - seccionar
    - reconstruir firmas/bitácora/tablas
    """

    def run(self, doc: Document, ctx) -> Document:
        pdf_path = Path(doc.source_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF no encontrado: {pdf_path}")

        agent_dir = Path(doc.workspace_doc_dir) / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)

        out_path = agent_dir / "pages_raw.json"

        reader = PdfReader(str(pdf_path))
        pages: List[Dict[str, Any]] = []

        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            # Normalización mínima: evita nulls y espacios extremos
            text = text.replace("\x00", "").strip()
            pages.append({"page": i, "text": text})

        out_path.write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")

        # meta útil
        if getattr(doc, "metadata", None) is None:
            doc.metadata = {}
        doc.metadata["page_count"] = len(pages)
        doc.metadata["agent_pages_raw"] = str(out_path)

        return doc
