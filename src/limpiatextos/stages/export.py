# src/limpiatextos/stages/export.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

from src.limpiatextos.core.models import ArtifactType, Document
from src.limpiatextos.pipeline.registry import stage
from src.limpiatextos.pipeline.stages import StageContext
from src.limpiatextos.core import logging as metrics


def _md_heading(level: int, title: str) -> str:
    lvl = max(1, min(6, int(level)))
    return ("#" * lvl) + " " + title.strip()


def _slug(s: str) -> str:
    s = s.strip().lower()
    s = "".join(ch if ch.isalnum() or ch in (" ", "-", "_") else "" for ch in s)
    s = s.replace(" ", "-")
    while "--" in s:
        s = s.replace("--", "-")
    return s[:80] or "section"


def _collect_toc(entries: List[str], node: Dict[str, Any], depth: int = 0, max_depth: int = 3) -> None:
    if depth >= max_depth:
        return
    title = node.get("title", "").strip()
    level = int(node.get("level", 2))
    if title:
        indent = "  " * max(0, (level - 2))
        entries.append(f"{indent}- [{title}](#{_slug(title)})")
    for ch in (node.get("children") or []):
        _collect_toc(entries, ch, depth + 1, max_depth=max_depth)


def _render_section_md(node: Dict[str, Any]) -> str:
    parts: List[str] = []
    title = (node.get("title") or "").strip()
    level = int(node.get("level", 2))

    if title:
        parts.append(_md_heading(level, title))
        parts.append("")

    content = node.get("content_md") or []
    if isinstance(content, list):
        for ln in content:
            parts.append(str(ln))

    # separador
    parts.append("")

    for ch in (node.get("children") or []):
        parts.append(_render_section_md(ch))

    return "\n".join(parts).rstrip() + "\n"


@dataclass
class ExportStage:
    name: str = "export"
    requires: Sequence[ArtifactType] = ("clean_text", "sections")
    produces: Sequence[ArtifactType] = ()
    idempotent: bool = True

    def run(self, doc: Document, ctx: StageContext) -> Document:
        doc.ensure_workspace()

        outputs_root = Path(ctx.outputs_root)
        out_text_dir = outputs_root / "text"
        out_md_dir = outputs_root / "md"
        out_jsonl_dir = outputs_root / "jsonl"
        out_reports_dir = outputs_root / "reports"

        for d in (out_text_dir, out_md_dir, out_jsonl_dir, out_reports_dir):
            d.mkdir(parents=True, exist_ok=True)

        # --- Export clean text (.txt) ---
        clean_text_path = doc.workspace_doc_dir / "clean_text.txt"
        out_txt = out_text_dir / f"{doc.doc_id}.txt"
        if clean_text_path.exists() and clean_text_path.stat().st_size > 0:
            out_txt.write_text(clean_text_path.read_text(encoding="utf-8"), encoding="utf-8")
            metrics.emit(doc.doc_id, "export_text_ok", True, tags={"stage": self.name})
        else:
            out_txt.write_text("", encoding="utf-8")
            metrics.emit(doc.doc_id, "export_text_ok", False, tags={"stage": self.name})

        # --- Export sections to structured markdown (.md) ---
        sections_path = doc.workspace_doc_dir / "sections.json"
        out_md = out_md_dir / f"{doc.doc_id}.md"

        md_parts: List[str] = []
        doc_title = doc.meta.get("source_filename", doc.doc_id)
        md_parts.append("# " + str(doc_title))
        md_parts.append("")
        md_parts.append(f"- doc_id: `{doc.doc_id}`")
        md_parts.append("")

        if sections_path.exists() and sections_path.stat().st_size > 0:
            payload = json.loads(sections_path.read_text(encoding="utf-8"))
            children = payload.get("children") or []
            # TOC
            toc_entries: List[str] = []
            for node in children:
                _collect_toc(toc_entries, node, max_depth=3)
            if toc_entries:
                md_parts.append("## Contenido")
                md_parts.append("")
                md_parts.extend(toc_entries)
                md_parts.append("")

            # Body
            for node in children:
                md_parts.append(_render_section_md(node))
            metrics.emit(doc.doc_id, "export_md_ok", True, tags={"stage": self.name})
        else:
            md_parts.append("## Contenido")
            md_parts.append("")
            md_parts.append("_No se generó estructura; exportando texto plano._")
            md_parts.append("")
            md_parts.append(out_txt.read_text(encoding="utf-8")[:50_000] if out_txt.exists() else "")
            metrics.emit(doc.doc_id, "export_md_ok", False, tags={"stage": self.name})

        out_md.write_text("\n".join(md_parts).rstrip() + "\n", encoding="utf-8")

        # --- Export chunks jsonl (compat: si existe sections.json con chunks antiguos, intentamos) ---
        out_jsonl = out_jsonl_dir / f"{doc.doc_id}.jsonl"
        # --- Export chunks jsonl ---
        chunks_path = doc.workspace_doc_dir / "chunks.json"
        if chunks_path.exists() and chunks_path.stat().st_size > 0:
            payload = json.loads(chunks_path.read_text(encoding="utf-8"))
            chunks = payload.get("chunks") or []
            with out_jsonl.open("w", encoding="utf-8") as f:
                for ch in chunks:
                    f.write(json.dumps(ch, ensure_ascii=False) + "\n")
            metrics.emit(doc.doc_id, "export_jsonl_ok", True, tags={"stage": self.name})

        elif sections_path.exists() and sections_path.stat().st_size > 0:
            payload = json.loads(sections_path.read_text(encoding="utf-8"))
            flat: List[Dict[str, Any]] = []

            def walk(n: Dict[str, Any]):
                text = "\n".join(n.get("content_md") or []).strip()
                if text:
                    flat.append({"chunk_id": len(flat) + 1, "title": n.get("title", ""), "level": n.get("level", 2), "text": text})
                for c in (n.get("children") or []):
                    walk(c)

            for n in (payload.get("children") or []):
                walk(n)

            with out_jsonl.open("w", encoding="utf-8") as f:
                for ch in flat:
                    f.write(json.dumps(ch, ensure_ascii=False) + "\n")
            metrics.emit(doc.doc_id, "export_jsonl_ok", True, tags={"stage": self.name})

        else:
            out_jsonl.write_text("", encoding="utf-8")
            metrics.emit(doc.doc_id, "export_jsonl_ok", False, tags={"stage": self.name})


        metrics.emit(doc.doc_id, "export_ok", True, tags={"stage": self.name})
        return doc


@stage("export", order=90)
def make_export() -> ExportStage:
    return ExportStage()
