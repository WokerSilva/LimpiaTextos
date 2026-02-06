from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

from limpiatextos.pipeline.runner import run_document
from limpiatextos.strategies.agent_corpus.artifacts import (
    AgentDocumentMetadata,
    BatchReport,
    CorpusIndex,
)

# -------------------------------------------------------------------
# Section anchors (where we want to INLINE-render tables)
# -------------------------------------------------------------------

SECTION_TITLE_RE = re.compile(
    r"^(Bitácora de cambios(?: y mejoras)?|Control de cambios|Historial de versiones|"
    r"Firmas electrónicas|Firmas|Aprobaciones|Responsables|"
    r"Enlace con documentos relacionados|Responsabilidades|Indicadores(?: de desempeño)?|"
    r"Riesgos y controles|Activos de información)\b",
    re.IGNORECASE,
)

# Next section headings like: "3. Objetivo", "11. Procedimiento", "I. Planeación" etc.
NEXT_SECTION_RE = re.compile(r"^\s*(\d+(\.\d+)*\.)\s+\S+")
ROMAN_SECTION_RE = re.compile(r"^\s*[IVXLC]+\.\s+\S+", re.IGNORECASE)

# Bitácora row parsing (fallback when detector collapses rows)
BITACORA_ROW_RE = re.compile(
    r"(?P<no>\d+)\s+"
    r"(?P<ver>\d+(?:\.\d+)*)\s+"
    r"(?P<date>\d{1,2}/\d{1,2}/\d{4})\s+"
    r"(?P<rest>.+?)"
    r"(?=(?:\s+\d+\s+\d+(?:\.\d+)*\s+\d{1,2}/\d{1,2}/\d{4}\s+)|$)",
    re.DOTALL,
)

# Stop phrases that should NOT be inside table content
STOP_PHRASE_IN_TABLE_RE = re.compile(
    r"\b(\d+(\.\d+)*\.\s+|Objetivo\b|Alcance\b|Normatividad\b|Procedimiento\b)\b",
    re.IGNORECASE,
)


# -------------------------------------------------------------------
# Paths helpers
# -------------------------------------------------------------------

def _agent_dir(doc_id: str) -> Path:
    return Path("workspace") / doc_id / "agent"


def _pages_clean_path(doc_id: str) -> Path:
    return _agent_dir(doc_id) / "pages_clean.jsonl"


def _tables_path(doc_id: str) -> Path:
    return _agent_dir(doc_id) / "tables.json"


def _meta_path(doc_id: str) -> Path:
    return _agent_dir(doc_id) / "meta.json"


# -------------------------------------------------------------------
# Table helpers
# -------------------------------------------------------------------

def _normalize_title(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").strip().lower())


def _load_tables(doc_id: str) -> List[Dict[str, Any]]:
    p = _tables_path(doc_id)
    if not p.exists() or p.stat().st_size == 0:
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _build_tables_index(
    tables: List[Dict[str, Any]]
) -> Dict[Tuple[int, str], Dict[str, Any]]:
    """
    Index by (page_start, normalized_title).
    If duplicates exist, prefer the one with more rows.
    """
    idx: Dict[Tuple[int, str], Dict[str, Any]] = {}
    for tb in tables:
        page_start = int(tb.get("page_start") or 0)
        title = _normalize_title(tb.get("section_title", ""))
        if not page_start or not title:
            continue

        key = (page_start, title)
        prev = idx.get(key)
        if prev is None:
            idx[key] = tb
        else:
            prev_rows = prev.get("rows") or []
            rows = tb.get("rows") or []
            if len(rows) > len(prev_rows):
                idx[key] = tb
    return idx


def _md_table(columns: List[str], rows: List[List[Any]]) -> str:
    def esc(x: Any) -> str:
        s = "" if x is None else str(x)
        s = s.replace("\\", "\\\\").replace("|", r"\|")
        s = re.sub(r"\s+", " ", s).strip()
        return s

    cols = [esc(c) for c in columns]
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"

    out = [header, sep]
    for r in rows:
        rr = [esc(c) for c in (r or [])]

        # normalize width
        if len(rr) < len(cols):
            rr += [""] * (len(cols) - len(rr))
        elif len(rr) > len(cols):
            rr = rr[: len(cols) - 1] + [" ".join(rr[len(cols) - 1 :])]

        out.append("| " + " | ".join(rr) + " |")
    return "\n".join(out) + "\n"


def _infer_columns_if_missing(rows: List[List[Any]]) -> List[str]:
    if not rows:
        return []
    width = max(len(r or []) for r in rows) if rows else 0
    if width <= 0:
        return []
    return [f"Col {i+1}" for i in range(width)]


def _fix_bitacora_rows_if_collapsed(
    columns: List[str], rows: List[List[Any]]
) -> List[List[str]]:
    """
    If detector gave something like one row containing the whole table text,
    try to split it into multiple canonical rows.
    Canonical columns expected: No., Versión, Fecha, Área responsable, Descripción
    """
    if not rows:
        return rows

    # If we already have multiple rows with date in col 3, keep as is.
    if len(rows) >= 2:
        return [[("" if c is None else str(c)) for c in r] for r in rows]

    # Single-row collapse: join all cells into one blob and parse.
    blob = " ".join("" if c is None else str(c) for c in (rows[0] or [])).strip()
    blob = re.sub(r"\s+", " ", blob)

    # Remove header if present
    blob = re.sub(
        r"\bNo\.\s+Versión\s+Fecha\s+Área\s+responsable\s+Descripción\b",
        "",
        blob,
        flags=re.IGNORECASE,
    ).strip()

    parsed: List[List[str]] = []
    for m in BITACORA_ROW_RE.finditer(blob):
        no = m.group("no").strip()
        ver = m.group("ver").strip()
        date = m.group("date").strip()
        rest = m.group("rest").strip()

        # Hard stop: if rest includes next-section heading cues, cut it
        stop = STOP_PHRASE_IN_TABLE_RE.search(rest)
        if stop:
            rest = rest[: stop.start()].strip()

        # Heuristic split: "Área responsable" tends to be words, desc is tail.
        # If we can’t reliably split, keep area empty and everything in desc.
        area = ""
        desc = rest

        # Try to split by two+ spaces if present (rare once normalized),
        # or by finding first sentence break.
        parts = re.split(r"\s{2,}", rest)
        if len(parts) >= 2:
            area = parts[0].strip()
            desc = " ".join(parts[1:]).strip()
        else:
            # Try split by " Emisión " / " Ajuste " / " Cambio " / " Actualización " cues
            cue = re.search(r"\b(Emisión|Ajuste|Cambio|Actualización|Revisión|Incorporación)\b", rest, re.IGNORECASE)
            if cue:
                area = rest[: cue.start()].strip()
                desc = rest[cue.start():].strip()

        parsed.append([no, ver, date, area, desc])

    return parsed if parsed else [[("" if c is None else str(c)) for c in r] for r in rows]


# -------------------------------------------------------------------
# Runner
# -------------------------------------------------------------------

class AgentCorpusRunner:
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
    # Markdown rendering
    # -------------------------

    def _render_footer_once(self, doc_id: str) -> str:
        meta_path = _meta_path(doc_id)
        if not meta_path.exists():
            return ""

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return ""

        if not meta.get("footer_detected"):
            return ""

        lines: List[str] = []
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
        pages_path = _pages_clean_path(doc_id)
        if not pages_path.exists():
            raise FileNotFoundError(f"No existe pages_clean.jsonl para {doc_id}: {pages_path}")

        tables = _load_tables(doc_id)
        tables_idx = _build_tables_index(tables)

        parts: List[str] = []

        # When we insert a table inline, we skip the raw/plain table text block
        skip_mode = False
        skip_until_section = True  # stop skipping when new section heading appears

        with pages_path.open("r", encoding="utf-8") as f:
            for line in f:
                obj = json.loads(line)
                page = int(obj.get("page", 0))
                text = (obj.get("text") or "")
                if not text.strip():
                    continue

                lines = [ln.rstrip("\n") for ln in text.splitlines()]

                i = 0
                while i < len(lines):
                    raw = lines[i]
                    ln = raw.strip()

                    if not ln:
                        # preserve paragraph breaks lightly
                        if not skip_mode:
                            parts.append("")
                        i += 1
                        continue

                    # If skipping original table block, stop when next real section begins
                    if skip_mode:
                        if SECTION_TITLE_RE.match(ln) or NEXT_SECTION_RE.match(ln) or ROMAN_SECTION_RE.match(ln):
                            skip_mode = False
                            # do not advance i -> re-process this line
                            continue
                        i += 1
                        continue

                    # Section title anchor (Bitácora, Activos, etc.)
                    m = SECTION_TITLE_RE.match(ln)
                    if m:
                        sec_title = m.group(0).strip()
                        parts.append(f"\n## {sec_title}\n")

                        key = (page, _normalize_title(sec_title))
                        tb = tables_idx.get(key)

                        if tb:
                            ttype = (tb.get("type") or "").strip().lower()
                            cols = tb.get("columns") or []
                            rows = tb.get("rows") or []

                            # Clean rows that accidentally swallow the rest of the document
                            # If any cell contains a clear "next section" cue, truncate the cell at that point.
                            cleaned_rows: List[List[Any]] = []
                            for r in rows:
                                rr = list(r) if r else []
                                new_rr: List[Any] = []
                                for c in rr:
                                    s = "" if c is None else str(c)
                                    cut = STOP_PHRASE_IN_TABLE_RE.search(s)
                                    if cut:
                                        s = s[: cut.start()].strip()
                                    new_rr.append(s)
                                cleaned_rows.append(new_rr)

                            rows = cleaned_rows

                            # If bitácora collapsed, re-split
                            if ttype == "bitacora_cambios" and cols:
                                rows = _fix_bitacora_rows_if_collapsed(cols, rows)

                            # Columns fallback if missing
                            if not cols:
                                cols = _infer_columns_if_missing(rows)

                            # Only render table if we have at least 2 cols and at least 1 row
                            if cols and len(cols) >= 2 and rows:
                                parts.append(_md_table(cols, rows))
                                parts.append("")
                                skip_mode = True
                            elif rows:
                                # fallback: structured list (keeps order)
                                for r in rows:
                                    if not r:
                                        continue
                                    parts.append("- " + " | ".join(str(x) for x in r if x is not None).strip())
                                parts.append("")
                                skip_mode = True

                        i += 1
                        continue

                    # Default body line
                    parts.append(ln)
                    i += 1

        # Normalize: collapse excessive blank lines
        out_lines: List[str] = []
        blank = 0
        for ln in parts:
            if ln.strip() == "":
                blank += 1
                if blank <= 1:
                    out_lines.append("")
            else:
                blank = 0
                out_lines.append(ln)

        return "\n".join(out_lines).strip() + "\n"

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
                    profile="default",
                    run_id=self.batch_id,
                )

                doc_id = run_result.doc_id

                md_body = self._render_md_from_agent_pages(doc_id) or ""
                md_footer = self._render_footer_once(doc_id) or ""

                # IMPORTANT: no md_tables prefix -> keep correct order
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
                import traceback
                traceback.print_exc()

        corpus_md_path = self._generate_corpus_md(documents)

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

    def _generate_corpus_md(self, documents: List[AgentDocumentMetadata]) -> Path:
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
