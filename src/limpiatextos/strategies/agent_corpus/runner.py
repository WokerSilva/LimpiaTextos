from __future__ import annotations

import time
from pathlib import Path
from typing import List
import json

import yaml

from limpiatextos.pipeline.runner import run_document
from limpiatextos.strategies.agent_corpus.artifacts import (
    AgentDocumentMetadata,
    CorpusIndex,
    BatchReport,
)


class AgentCorpusRunner:
    def _render_footer_once(self, doc_id: str) -> str:
        meta_path = Path("workspace") / doc_id / "agent" / "meta.json"
        if not meta_path.exists():
            return ""

            meta = json.loads(meta_path.read_text(encoding="utf-8"))

            if not meta.get("footer_detected"):
                return ""

            lines = []
            if meta.get("doc_code"):
                lines.append(f"- **Código:** {meta['doc_code']}")
            if meta.get("version"):
                lines.append(f"- **Versión:** {meta['version']}")
            if meta.get("raw_date"):
                lines.append(f"- **Fecha:** {meta['raw_date']}")
            if meta.get("classification"):
                lines.append(f"- **Clasificación:** {meta['classification']}")

            if not lines:
                return ""

            return (
                "\n\n---\n\n"
                "### ℹ️ Información del documento\n\n"
                + "\n".join(lines)
                + "\n"
            )

    def _render_md_from_agent_pages(self, doc_id: str) -> str:
        """
        Renderiza un MD simple usando SOLO agent/pages_clean.jsonl
        (sin portada, sin índice, sin pie).
        """
        agent_pages = (
            Path("workspace")
            / doc_id
            / "agent"
            / "pages_clean.jsonl"
        )

        if not agent_pages.exists():
            raise FileNotFoundError(f"No existe pages_clean.jsonl para {doc_id}")

        parts = []

        with agent_pages.open("r", encoding="utf-8") as f:
            for line in f:
                obj = json.loads(line)
                text = (obj.get("text") or "").strip()
                if not text:
                    continue
                parts.append(text)

        # separador simple entre páginas (temporal)
        return "\n\n".join(parts)

    def __init__(
        self,
        batch_dir: Path,
        outputs_dir: Path,
        strategy_name: str = "agent_corpus",
    ):
        self.batch_dir = batch_dir
        self.pdf_dir = batch_dir / "pdfs"
        self.batch_config_path = batch_dir / "batch.yaml"

        self.batch_id = batch_dir.name
        self.outputs_dir = outputs_dir / self.batch_id
        self.md_output_dir = self.outputs_dir / "md"

        self.strategy_name = strategy_name

        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.md_output_dir.mkdir(parents=True, exist_ok=True)

        self.batch_config = self._load_batch_config()

    # -------------------------
    # Public API
    # -------------------------

    def run(self):
        start_time = time.time()

        pdfs = sorted(self.pdf_dir.glob("*.pdf"))
        total = len(pdfs)

        print(f"[AgentCorpus] Lote: {self.batch_id}")
        print(f"[AgentCorpus] PDFs detectados: {total}\n")

        documents: List[AgentDocumentMetadata] = []
        failed = 0

        for idx, pdf_path in enumerate(pdfs, start=1):
            print(f"[{idx}/{total}] Procesando {pdf_path.name} ... ", end="")


            try:
                run_result = run_document(
                    source_pdf=str(pdf_path),
                    profile="default",  # luego lo conectamos a pipeline_spec.yaml
                    run_id=self.batch_id,
                )

                doc_id = run_result.doc_id

                md_body = self._render_md_from_agent_pages(doc_id)
                md_footer = self._render_footer_once(doc_id)
                md_text = md_body + md_footer
                target_md = self.md_output_dir / f"{doc_id}.md"
                target_md.write_text(md_text, encoding="utf-8")

                metadata = AgentDocumentMetadata(
                    doc_id=doc_id,
                    source_pdf=pdf_path.name,
                    md_filename=target_md.name,
                    title=getattr(run_result, "title", None),
                    language=getattr(run_result, "language", None),
                    sections=getattr(run_result, "sections", []),
                    signals=getattr(run_result, "signals", {}),
                    qa_flags=getattr(run_result, "qa_flags", {}),
                )

                documents.append(metadata)

                print("OK")

            except Exception as e:
                failed += 1
                print(f"FAIL ({e})")

        # Generar corpus final
        corpus_md_path = self._generate_corpus_md(documents)

        # Reporte de lote
        duration = time.time() - start_time

        batch_report = BatchReport(
            batch_id=self.batch_id,
            total_documents=total,
            processed_documents=len(documents),
            failed_documents=failed,
            started_at=time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(start_time)),
            finished_at=time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
            duration_seconds=round(duration, 2),
        )

        corpus_index = CorpusIndex(
            corpus_id=self.batch_id,
            documents=documents,
            batch_report=batch_report,
        )

        corpus_index_path = self.outputs_dir / "corpus_index.json"
        corpus_index.to_json(corpus_index_path)

        batch_report_path = self.outputs_dir / "batch_report.json"
        batch_report_path.write_text(
            yaml.safe_dump(batch_report.to_dict(), allow_unicode=True),
            encoding="utf-8",
        )

        print("\n✔ Lote completado")
        print(f"✔ corpus.md generado: {corpus_md_path}")
        print(f"✔ corpus_index.json generado")
        print(f"✔ batch_report.json generado")

    # -------------------------
    # Internals
    # -------------------------

    def _load_batch_config(self) -> dict:
        if not self.batch_config_path.exists():
            return {}

        return yaml.safe_load(self.batch_config_path.read_text(encoding="utf-8"))

    def _generate_corpus_md(
        self, documents: List[AgentDocumentMetadata]
    ) -> Path:
        corpus_md_path = self.outputs_dir / "corpus.md"

        separator = "\n\n==================================================\n\n"

        parts: List[str] = []
        parts.append(f"# 📚 Corpus — {self.batch_id}\n")

        for doc in documents:
            md_path = self.md_output_dir / doc.md_filename
            if not md_path.exists():
                continue

            parts.append(separator)
            parts.append(md_path.read_text(encoding="utf-8"))

        corpus_md_path.write_text("".join(parts), encoding="utf-8")

        return corpus_md_path
