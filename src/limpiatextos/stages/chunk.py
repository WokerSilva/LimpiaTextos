# src/limpiatextos/stages/chunk.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

from limpiatextos.core.models import Artifact, ArtifactType, Document
from limpiatextos.pipeline.registry import stage
from limpiatextos.pipeline.stages import StageContext
from limpiatextos.core import logging as metrics


def _approx_tokens(text: str) -> int:
    return max(1, int(len(text) / 4))


def _split_paragraphs(text: str) -> List[str]:
    parts = re.split(r"\n\s*\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _pack_chunks(paragraphs: List[str], *, min_tokens: int, target_tokens: int, max_tokens: int) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    buf: List[str] = []
    buf_tokens = 0

    def flush():
        nonlocal buf, buf_tokens
        if not buf:
            return
        text = "\n\n".join(buf).strip()
        chunks.append({"text": text, "tokens_approx": _approx_tokens(text), "chars": len(text)})
        buf = []
        buf_tokens = 0

    for p in paragraphs:
        pt = _approx_tokens(p)

        if pt > max_tokens:
            flush()
            sentences = re.split(r"(?<=[\.\!\?])\s+", p)
            s_buf: List[str] = []
            s_tokens = 0
            for s in sentences:
                s = s.strip()
                if not s:
                    continue
                st = _approx_tokens(s)
                if s_tokens + st > max_tokens and s_buf:
                    text = " ".join(s_buf).strip()
                    chunks.append({"text": text, "tokens_approx": _approx_tokens(text), "chars": len(text)})
                    s_buf, s_tokens = [], 0
                s_buf.append(s)
                s_tokens += st
            if s_buf:
                text = " ".join(s_buf).strip()
                chunks.append({"text": text, "tokens_approx": _approx_tokens(text), "chars": len(text)})
            continue

        if buf_tokens + pt > max_tokens and buf:
            flush()

        buf.append(p)
        buf_tokens += pt

        if buf_tokens >= target_tokens and buf_tokens >= min_tokens:
            flush()

    flush()

    for idx, ch in enumerate(chunks, start=1):
        ch["chunk_id"] = idx
    return chunks


@dataclass
class ChunkStage:
    name: str = "chunk"
    requires: Sequence[ArtifactType] = ("clean_text",)
    produces: Sequence[ArtifactType] = ("chunks",)
    idempotent: bool = True

    def run(self, doc: Document, ctx: StageContext) -> Document:
        doc.ensure_workspace()
        clean_text_path = doc.workspace_doc_dir / "clean_text.txt"

        out_path = doc.workspace_doc_dir / "chunks.json"

        if not clean_text_path.exists() or clean_text_path.stat().st_size == 0:
            metrics.emit(doc.doc_id, "chunk_input_missing", True, tags={"stage": self.name})
            out_path.write_text(json.dumps({"doc_id": doc.doc_id, "chunks": []}, ensure_ascii=False, indent=2), encoding="utf-8")
            doc.register_artifact(Artifact(type="chunks", path="chunks.json", mime="application/json"))
            metrics.emit(doc.doc_id, "chunks_count", 0, tags={"stage": self.name})
            metrics.emit(doc.doc_id, "chunk_ok", False, tags={"stage": self.name})
            return doc

        text = clean_text_path.read_text(encoding="utf-8").strip()

        chunks_cfg = (ctx.config.get("chunks") or {})
        min_chars_chunk = int(chunks_cfg.get("min_chars_chunk", 50))
        min_tokens = int(chunks_cfg.get("avg_chunk_tokens_min", 300))
        max_tokens = int(chunks_cfg.get("avg_chunk_tokens_max", 800))
        target_tokens = int((min_tokens + max_tokens) / 2)

        paragraphs = _split_paragraphs(text)
        chunks = _pack_chunks(paragraphs, min_tokens=min_tokens, target_tokens=target_tokens, max_tokens=max_tokens)
        chunks = [c for c in chunks if c.get("chars", 0) >= min_chars_chunk]

        payload = {"doc_id": doc.doc_id, "chunks": chunks}
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        doc.register_artifact(Artifact(type="chunks", path="chunks.json", mime="application/json", meta={"producer": "chunk"}))

        chunks_count = len(chunks)
        avg_tokens = int(sum(c["tokens_approx"] for c in chunks) / chunks_count) if chunks_count else 0

        metrics.emit(doc.doc_id, "chunks_count", chunks_count, tags={"stage": self.name})
        metrics.emit(doc.doc_id, "avg_chunk_tokens_approx", avg_tokens, tags={"stage": self.name})
        metrics.set_meta(doc.doc_id, "chunks_count", chunks_count)

        metrics.emit(doc.doc_id, "chunk_ok", True, tags={"stage": self.name})
        return doc


@stage("chunk", order=85)
def make_chunk() -> ChunkStage:
    return ChunkStage()
