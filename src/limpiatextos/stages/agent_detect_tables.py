
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

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

from limpiatextos.core.models import Artifact, ArtifactType, Document
from limpiatextos.pipeline.registry import stage
from limpiatextos.pipeline.stages import StageContext
from limpiatextos.core import logging as metrics

def _agent_dir(doc: Document) -> Path:
    return doc.workspace_doc_dir / "agent"


def _pages_clean_path(doc: Document) -> Path:
    return _agent_dir(doc) / "pages_clean.jsonl"


def _tables_path(doc: Document) -> Path:
    return _agent_dir(doc) / "tables.json"


# -------------------------
# Heurísticas y patrones
# -------------------------

SECTION_TITLE_RE = re.compile(
    r"^(Bitácora de cambios|Control de cambios|Historial de versiones|"
    r"Firmas electrónicas|Firmas|Aprobaciones|Responsables|"
    r"Enlace con documentos relacionados|Responsabilidades|Indicadores|"
    r"Riesgos y controles|Activos de información)\b",
    re.IGNORECASE,
)

# Header típico de bitácora
BITACORA_HEADER_RE = re.compile(
    r"No\.\s+Versión\s+Fecha\s+Área\s+responsable\s+Descripción",
    re.IGNORECASE,
)

# Inicio de fila de bitácora: comienza con número
ROW_START_RE = re.compile(r"^\d+\s+")

# Heading real (para cortar tabla)
REAL_HEADING_RE = re.compile(r"^\d+(\.\d+)*\s+\w+")


# -------------------------
# Stage
# -------------------------

@dataclass
class AgentDetectTablesStage:
    name: str = "agent_detect_tables"
    requires: Sequence[ArtifactType] = ("agent_pages_clean",)
    produces: Sequence[ArtifactType] = ("agent_tables",)
    idempotent: bool = True

    def run(self, doc: Document, ctx: StageContext) -> Document:
        pages_path = _pages_clean_path(doc)
        if not pages_path.exists():
            raise FileNotFoundError(f"No existe pages_clean.jsonl: {pages_path}")

        out_path = _tables_path(doc)
        agent_dir = _agent_dir(doc)
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Reusar si existe
        if out_path.exists() and out_path.stat().st_size > 0:
            metrics.emit(doc.doc_id, "agent_tables_reused", True, tags={"stage": self.name})
            doc.register_artifact(
                Artifact(
                    type="agent_tables",
                    path=str(out_path.relative_to(doc.workspace_doc_dir)),
                    mime="application/json",
                    meta={"producer": self.name, "method": "reuse"},
                )
            )
            return doc

        tables: List[Dict[str, Any]] = []

        current_table: Dict[str, Any] | None = None
        current_rows: List[List[str]] = []
        current_columns: List[str] = []

        with pages_path.open("r", encoding="utf-8") as f:
            for line in f:
                obj = json.loads(line)
                page = obj["page"]
                text = obj["text"]

                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

                for ln in lines:
                    # 1) ¿Inicio de sección tabular?
                    m_sec = SECTION_TITLE_RE.match(ln)
                    if m_sec:
                        # Si estamos en bitácora, ignoramos títulos falsos dentro del bloque
                        if current_table and current_table.get("type") == "bitacora_cambios":
                            # Solo cerramos bitácora si el título detectado NO es parte del texto de tabla
                            # (en MVP: ignorar completamente)
                            continue
                        # cerrar tabla anterior y marcar page_end
                        if current_table:
                            current_table["rows"] = current_rows
                            current_table["page_end"] = page
                            tables.append(current_table)

                        current_table = {
                            "section_title": m_sec.group(0),
                            "page_start": page,
                            "type": self._infer_table_type(m_sec.group(0)),
                            "columns": [],
                            "rows": [],
                        }
                        current_rows = []
                        current_columns = []
                        continue

                    # 2) Header de bitácora
                    if current_table and BITACORA_HEADER_RE.search(ln):
                        current_columns = [
                            "No.",
                            "Versión",
                            "Fecha",
                            "Área responsable",
                            "Descripción",
                        ]
                        current_table["columns"] = current_columns
                        continue


                    # 3) Inicio de fila (bitácora robusta)
                    if current_table and current_table.get("type") == "bitacora_cambios":
                        m = BITACORA_ROW_PREFIX_RE.match(ln)
                        if m:
                            no = m.group("no")
                            ver = m.group("ver")
                            date = m.group("date")
                            rest = m.group("rest").strip()

                            # Evitar contaminación si el resto contiene heading de sección
                            # (caso: "11. Procedimiento ...")
                            if BITACORA_STOP_HEADING_RE.search(rest):
                                # corta antes del heading
                                rest = re.split(r"\b\d+\.\s+", rest, maxsplit=1)[0].strip()

                            # dividir rest en area + desc usando palabras guía
                            mm = BITACORA_DESC_CUE_RE.search(rest)
                            if mm:
                                area = rest[: mm.start()].strip()
                                desc = rest[mm.start():].strip()
                            else:
                                # fallback: si no detecta cue, todo a desc
                                area = ""
                                desc = rest

                            current_rows.append([no, ver, date, area, desc])
                            continue
                    # 3) Inicio de fila (otros casos, EXCLUYE bitácora)
                    if (
                        current_table
                        and current_table.get("type") != "bitacora_cambios"
                        and ROW_START_RE.match(ln)
                    ):
                        cells = self._split_row(ln, len(current_columns))
                        current_rows.append(cells)
                        continue

                    # 4) Continuación de celda (descripción larga)
                    if current_table and current_rows:
                        # Si aparece un heading real, cerramos tabla
                        if REAL_HEADING_RE.match(ln):
                            current_table["rows"] = current_rows
                            current_table["page_end"] = page
                            tables.append(current_table)
                            current_table = None
                            current_rows = []
                            current_columns = []
                            continue

                        # concatenar a última celda
                        current_rows[-1][-1] += " " + ln.strip()
                        continue

        # cerrar tabla final
        if current_table:
            current_table["rows"] = current_rows
            tables.append(current_table)

        out_path.write_text(json.dumps(tables, ensure_ascii=False, indent=2), encoding="utf-8")

        metrics.emit(doc.doc_id, "agent_tables_detected", len(tables), tags={"stage": self.name})

        doc.register_artifact(
            Artifact(
                type="agent_tables",
                path=str(out_path.relative_to(doc.workspace_doc_dir)),
                mime="application/json",
                meta={"producer": self.name, "method": "heuristic"},
            )
        )

        return doc

    # -------------------------
    # Helpers
    # -------------------------

    def _infer_table_type(self, title: str) -> str:
        t = title.lower()
        if "bitácora" in t or "cambios" in t:
            return "bitacora_cambios"
        if "firma" in t or "aprob" in t:
            return "firmas"
        if "enlace" in t:
            return "enlace_documentos"
        if "responsabil" in t:
            return "responsabilidades"
        if "indicador" in t:
            return "indicadores"
        if "riesgo" in t:
            return "riesgos_controles"
        if "activo" in t:
            return "activos_informacion"
        return "tabla_generica"

    def _split_row(self, line: str, expected_cols: int) -> List[str]:
        # dividir por espacios múltiples
        parts = re.split(r"\s{2,}", line)
        parts = [p.strip() for p in parts if p.strip()]

        # ajustar número de columnas
        if expected_cols and len(parts) > expected_cols:
            head = parts[: expected_cols - 1]
            tail = [" ".join(parts[expected_cols - 1 :])]
            return head + tail

        if expected_cols and len(parts) < expected_cols:
            parts += [""] * (expected_cols - len(parts))

        return parts


@stage("agent_detect_tables", order=80)
def make_agent_detect_tables() -> AgentDetectTablesStage:
    return AgentDetectTablesStage()
