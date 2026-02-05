# src/limpiatextos/pipeline/runner.py
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.limpiatextos.core.models import Document
from src.limpiatextos.pipeline.registry import REGISTRY
from src.limpiatextos.pipeline.stages import StageContext, can_skip_stage, ensure_workspace_layout

# metrics/logging (stubs)
from src.limpiatextos.core import logging as metrics


@dataclass
class RunResult:
    doc_id: str
    status: str  # OK | FAIL
    executed_stages: List[str]
    skipped_stages: List[str]
    started_at: float
    finished_at: float
    workspace_doc_dir: str
    manifest_path: str
    report_path: str


def _load_yaml_if_available(path: Path) -> Dict[str, Any]:
    """
    Carga YAML si PyYAML está disponible; si no, falla con mensaje claro.
    (Mantiene offline y simple.)
    """
    try:
        import yaml  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "PyYAML no está instalado. Agrega 'pyyaml' a pyproject.toml para cargar configs/*.yaml"
        ) from e

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _resolve_config(configs_dir: str, profile: str) -> Dict[str, Any]:
    """
    Convención: configs/<profile>.yaml
    Ej: default.yaml, codespaces.yaml, high_accuracy.yaml
    """
    cfg_path = Path(configs_dir) / f"{profile}.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config profile not found: {cfg_path}")
    cfg = _load_yaml_if_available(cfg_path)
    cfg["_profile"] = profile
    cfg["_path"] = str(cfg_path)
    return cfg


def run_document(
    source_pdf: str,
    *,
    workspace_root: str = "workspace",
    outputs_root: str = "outputs",
    configs_dir: str = "configs",
    profile: str = "default",
    include_stages: Optional[Sequence[str]] = None,
    exclude_stages: Optional[Sequence[str]] = None,
    stage_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    run_id: str = "default",
) -> RunResult:
    """
    Ejecuta el pipeline para un PDF.

    - Genera doc_id estable (sha256 del archivo) en Document.from_source()
    - Crea workspace/<doc_id>/
    - Escribe manifest.json antes y después de ejecutar stages
    - Emite métricas por stage y persiste report.json al final
    """
    started_at = time.time()

    config = _resolve_config(configs_dir, profile)
    doc = Document.from_source(source_pdf, workspace_root)
    doc.ensure_workspace()
    ensure_workspace_layout(doc)

    # meta base
    metrics.set_meta(doc.doc_id, "doc_id", doc.doc_id)
    metrics.set_meta(doc.doc_id, "source_filename", Path(doc.source_path).name)
    metrics.set_meta(doc.doc_id, "workspace_doc_dir", str(doc.workspace_doc_dir))
    metrics.set_meta(doc.doc_id, "config_profile", profile)
    metrics.set_meta(doc.doc_id, "config_path", config.get("_path", ""))
    metrics.set_meta(doc.doc_id, "run_id", run_id)

    # guardar manifest inicial
    manifest_path = doc.write_manifest()
    metrics.emit(doc.doc_id, "manifest_written", True, tags={"stage": "runner"})

    ctx = StageContext(
        config=config,
        workspace_root=Path(workspace_root),
        outputs_root=Path(outputs_root),
        run_id=run_id,
        extras={},
    )

    # Merge stage overrides from config and caller
    cfg_overrides = ((config.get("pipeline") or {}).get("stage_overrides") or {})
    merged_overrides = dict(cfg_overrides)
    if stage_overrides:
        # stage_overrides from the caller takes precedence over config
        for k, v in stage_overrides.items():
            merged_overrides[k] = {**merged_overrides.get(k, {}), **(v or {})}

    pipeline = REGISTRY.build_pipeline(
        include=include_stages,
        exclude=exclude_stages,
        overrides=merged_overrides,
    )

    executed: List[str] = []
    skipped: List[str] = []
    status = "OK"

    for stg in pipeline:
        stage_name = getattr(stg, "name", stg.__class__.__name__)
        # permitir skip si idempotente y outputs listos
        if can_skip_stage(doc, stg):
            skipped.append(stage_name)
            metrics.emit(doc.doc_id, "stage_skipped", True, tags={"stage": stage_name})
            continue

        try:
            with metrics.stage_timer(doc.doc_id, stage_name):
                doc = stg.run(doc, ctx)
            executed.append(stage_name)
            # persistimos manifest después de cada stage (robusto)
            doc.write_manifest()
        except Exception as e:
            status = "FAIL"
            metrics.emit(doc.doc_id, "pipeline_error", str(e), tags={"stage": stage_name})
            # re-escribe manifest al fallo para inspección post-mortem
            doc.write_manifest()
            break

    finished_at = time.time()

    # meta final
    metrics.set_meta(doc.doc_id, "pipeline_status", status)
    metrics.set_meta(doc.doc_id, "pipeline_started_at", started_at)
    metrics.set_meta(doc.doc_id, "pipeline_finished_at", finished_at)
    metrics.set_meta(doc.doc_id, "pipeline_duration_seconds", finished_at - started_at)
    metrics.set_meta(doc.doc_id, "executed_stages", executed)
    metrics.set_meta(doc.doc_id, "skipped_stages", skipped)

    # persistir report.json en workspace/<doc_id>/
    report_path = metrics.flush_report(doc.doc_id, str(doc.workspace_doc_dir))

    return RunResult(
        doc_id=doc.doc_id,
        status=status,
        executed_stages=executed,
        skipped_stages=skipped,
        started_at=started_at,
        finished_at=finished_at,
        workspace_doc_dir=str(doc.workspace_doc_dir),
        manifest_path=str(manifest_path),
        report_path=str(report_path),
    )
