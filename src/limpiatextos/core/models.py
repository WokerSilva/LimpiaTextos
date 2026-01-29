# src/limpiatextos/core/models.py
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional


ArtifactType = Literal[
    "manifest",
    "plan",
    "normalized_pdf",
    "raw_text_pages",
    "clean_text",
    "clean_text_pages",
    "sections",
    "tables_index",
    "figures_index",
    "report",
]


def stable_doc_id_from_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """
    Crea doc_id estable basado en hash del archivo.
    Nota: para PDFs grandes, se lee por chunks.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return f"sha256:{h.hexdigest()}"


@dataclass(frozen=True)
class Artifact:
    """
    Representa un archivo generado en workspace/<doc_id>/...
    """
    type: ArtifactType
    path: str  # relativo a workspace/<doc_id> (ej. "manifest.json", "tables/t1.png")
    mime: str = "application/octet-stream"
    meta: Dict[str, Any] = field(default_factory=dict)

    def abs_path(self, workspace_doc_dir: Path) -> Path:
        return workspace_doc_dir / self.path


@dataclass
class Page:
    """
    Página lógica del documento (cuando aplica).
    """
    page_num: int
    char_count: int = 0
    has_text: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    """
    Contenedor principal de ejecución por documento.
    - source_path: ruta al PDF de entrada
    - doc_id: id estable (hash)
    - workspace_doc_dir: workspace/<doc_id>/
    - artifacts: índice de artefactos producidos por stages
    - meta: metadatos (pages_total, ocr_used, etc)
    """
    source_path: str
    workspace_root: str
    doc_id: str
    artifacts: Dict[str, Artifact] = field(default_factory=dict)  # key = artifact.type
    pages: List[Page] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_source(source_path: str, workspace_root: str, doc_id: Optional[str] = None) -> "Document":
        src = Path(source_path)
        ws = Path(workspace_root)

        if doc_id is None:
            doc_id = stable_doc_id_from_file(src)

        doc = Document(
            source_path=str(src),
            workspace_root=str(ws),
            doc_id=doc_id,
        )
        doc.meta["source_filename"] = src.name
        return doc

    @property
    def workspace_doc_dir(self) -> Path:
        return Path(self.workspace_root) / self.doc_id

    def ensure_workspace(self) -> None:
        self.workspace_doc_dir.mkdir(parents=True, exist_ok=True)

    # --- Artifact helpers ---

    def register_artifact(self, artifact: Artifact) -> None:
        """
        Registra/actualiza el artifact por type.
        Convención: artifact.path es relativo a workspace/<doc_id>.
        """
        self.artifacts[artifact.type] = artifact

    def artifact_path(self, artifact_type: ArtifactType) -> Path:
        """
        Devuelve ruta absoluta del artifact dentro de workspace/<doc_id>.
        """
        art = self.artifacts.get(artifact_type)
        if not art:
            raise KeyError(f"Artifact not registered: {artifact_type}")
        return art.abs_path(self.workspace_doc_dir)

    # --- Manifest I/O ---

    def manifest_path(self) -> Path:
        return self.workspace_doc_dir / "manifest.json"

    def to_manifest_dict(self) -> Dict[str, Any]:
        """
        Manifest mínimo, estable y fácil de versionar.
        """
        return {
            "doc_id": self.doc_id,
            "source_path": self.source_path,
            "workspace_doc_dir": str(self.workspace_doc_dir),
            "meta": self.meta,
            "artifacts": {k: asdict(v) for k, v in self.artifacts.items()},
            "pages": [asdict(p) for p in self.pages],
        }

    def write_manifest(self) -> Path:
        self.ensure_workspace()
        p = self.manifest_path()
        p.write_text(json.dumps(self.to_manifest_dict(), ensure_ascii=False, indent=2))
        return p

    @staticmethod
    def load_from_manifest(manifest_path: str) -> "Document":
        p = Path(manifest_path)
        data = json.loads(p.read_text(encoding="utf-8"))

        doc = Document(
            source_path=data["source_path"],
            workspace_root=str(Path(data["workspace_doc_dir"]).parent),
            doc_id=data["doc_id"],
            meta=data.get("meta", {}),
        )

        # artifacts
        for k, v in (data.get("artifacts") or {}).items():
            doc.artifacts[k] = Artifact(**v)

        # pages
        doc.pages = [Page(**pp) for pp in (data.get("pages") or [])]
        return doc
