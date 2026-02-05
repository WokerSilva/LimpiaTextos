# src/limpiatextos/pipeline/stages.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Sequence

from limpiatextos.core.models import ArtifactType, Document


@dataclass(frozen=True)
class StageContext:
    """
    Contexto de ejecución compartido por stages.
    - config: config cargada (ej. configs/default.yaml)
    - workspace_root: raíz workspace/
    - outputs_root: raíz outputs/
    - run_id: id de ejecución (opcional; útil para trazabilidad)
    - extras: contenedor libre para inyectar dependencias (p.ej. ocr engine)
    """
    config: Dict[str, Any]
    workspace_root: Path
    outputs_root: Path
    run_id: str = "default"
    extras: Dict[str, Any] = field(default_factory=dict)


class Stage(Protocol):
    """
    Contrato de un stage: ejecuta transformaciones y registra artifacts/metrics.
    """
    name: str

    # Inputs/outputs declarativos (para validate/plan)
    requires: Sequence[ArtifactType]
    produces: Sequence[ArtifactType]

    # Si True, el stage puede saltarse si outputs existen y son válidos.
    idempotent: bool

    def run(self, doc: Document, ctx: StageContext) -> Document:
        ...


@dataclass
class StageSpec:
    """
    Especificación para construir/registrar un stage.
    - factory: función que retorna una instancia Stage.
    """
    name: str
    factory: Callable[[], Stage]
    enabled: bool = True
    order: int = 0
    tags: Dict[str, str] = field(default_factory=dict)


def ensure_workspace_layout(doc: Document) -> None:
    """
    Garantiza que existan subcarpetas opcionales que los stages podrían usar.
    """
    doc.ensure_workspace()
    (doc.workspace_doc_dir / "tables").mkdir(parents=True, exist_ok=True)
    (doc.workspace_doc_dir / "figures").mkdir(parents=True, exist_ok=True)


def artifact_exists_and_nonempty(doc: Document, artifact_type: ArtifactType) -> bool:
    """
    Check simple para idempotencia: existe y tiene tamaño > 0.
    (Validaciones profundas irán en validate/qa.)
    """
    try:
        p = doc.artifact_path(artifact_type)
    except KeyError:
        return False
    return p.exists() and p.is_file() and p.stat().st_size > 0


def can_skip_stage(doc: Document, stage: Stage) -> bool:
    """
    Un stage idempotente puede saltarse si todos sus outputs existen.
    """
    if not getattr(stage, "idempotent", False):
        return False
    produces = getattr(stage, "produces", []) or []
    if not produces:
        return False
    return all(artifact_exists_and_nonempty(doc, a) for a in produces)
