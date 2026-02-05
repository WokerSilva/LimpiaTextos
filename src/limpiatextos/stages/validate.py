# src/limpiatextos/stages/validate.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from limpiatextos.core.models import Artifact, ArtifactType, Document
from limpiatextos.core.qa import compute_overall_flag, load_thresholds
from limpiatextos.pipeline.registry import stage
from limpiatextos.pipeline.stages import StageContext
from limpiatextos.core import logging as metrics


@dataclass
class ValidateStage:
    name: str = "validate"
    requires: Sequence[ArtifactType] = ("manifest",)
    produces: Sequence[ArtifactType] = ("report",)
    idempotent: bool = False  # queremos recalcular QA siempre

    def run(self, doc: Document, ctx: StageContext) -> Document:
        doc.ensure_workspace()

        # 1) cargar thresholds
        thresholds = load_thresholds(configs_dir=str(Path("configs")))

        # 2) obtener reporte actual en memoria (emitido por pipeline)
        doc_report = metrics.get_doc_report(doc.doc_id)

        # 3) computar QA
        qa = compute_overall_flag(doc_report, thresholds)

        # 4) enriquecer reporte y persistir en workspace/<doc_id>/report.json
        report_path = doc.workspace_doc_dir / "report.json"

        # Si ya existe report.json, úsalo como base; si no, usa doc_report
        base = doc_report
        if report_path.exists() and report_path.stat().st_size > 0:
            try:
                base = json.loads(report_path.read_text(encoding="utf-8"))
            except Exception:
                base = doc_report

        base.setdefault("qa", {})
        base["qa"] = {
            "overall_flag": qa.overall_flag,
            "reasons": qa.reasons,
        }

        # también en meta
        base.setdefault("meta", {})
        base["meta"]["overall_flag"] = qa.overall_flag

        report_path.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")

        # 5) copiar a outputs/reports/<doc_id>.json
        out_reports = Path(ctx.outputs_root) / "reports"
        out_reports.mkdir(parents=True, exist_ok=True)
        out_path = out_reports / f"{doc.doc_id}.json"
        out_path.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")

        # 6) registrar artifact + emitir métrica
        doc.register_artifact(Artifact(type="report", path="report.json", mime="application/json", meta={"qa": True}))

        metrics.set_meta(doc.doc_id, "overall_flag", qa.overall_flag)
        metrics.emit(doc.doc_id, "overall_flag", qa.overall_flag, tags={"stage": self.name})
        metrics.emit(doc.doc_id, "validate_ok", True, tags={"stage": self.name})

        return doc


@stage("validate", order=95)
def make_validate() -> ValidateStage:
    return ValidateStage()
