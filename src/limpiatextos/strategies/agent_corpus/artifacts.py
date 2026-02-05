from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from datetime import datetime
import json


# -----------------------------
# Documento individual del corpus
# -----------------------------

@dataclass
class AgentDocumentMetadata:
    doc_id: str
    source_pdf: str
    md_filename: str

    title: Optional[str] = None
    language: Optional[str] = None

    sections: List[str] = field(default_factory=list)

    signals: Dict[str, object] = field(default_factory=dict)
    qa_flags: Dict[str, object] = field(default_factory=dict)

    included_in_corpus: bool = True

    def to_dict(self) -> Dict:
        return asdict(self)


# -----------------------------
# Reporte por lote
# -----------------------------

@dataclass
class BatchReport:
    batch_id: str
    total_documents: int
    processed_documents: int
    failed_documents: int

    warnings: List[str] = field(default_factory=list)

    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_seconds: Optional[float] = None

    def to_dict(self) -> Dict:
        return asdict(self)


# -----------------------------
# Índice completo del corpus
# -----------------------------

@dataclass
class CorpusIndex:
    corpus_id: str
    strategy: str = "agent_corpus"
    version: str = "0.1.0"

    generated_at: str = field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )

    source: str = "pdf_batch"

    documents: List[AgentDocumentMetadata] = field(default_factory=list)

    batch_report: Optional[BatchReport] = None

    def to_dict(self) -> Dict:
        return {
            "corpus_id": self.corpus_id,
            "strategy": self.strategy,
            "version": self.version,
            "generated_at": self.generated_at,
            "source": self.source,
            "documents": [d.to_dict() for d in self.documents],
            "batch_report": self.batch_report.to_dict()
            if self.batch_report
            else None,
        }

    def to_json(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
