# src/limpiatextos/core/logging.py
"""
Stubs ligeros para emitir métricas por documento/stage.
- metrics.emit(doc_id, name, value, tags={})
- stage_timer context manager para medir duracion de un stage.
- metrics.flush_report(doc_id, workspace_path) para persistir report final.
Diseñado para ser simple y extensible (logs JSON + report file).
"""

from __future__ import annotations
import json
import logging
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("limpiatextos.metrics")
logger.setLevel(logging.INFO)

# In-memory store: { doc_id: { "metrics": {name: [...values] }, "meta": {...}, "samples": [...] } }
_store: Dict[str, Dict[str, Any]] = {}
_store_lock = threading.Lock()


def _ensure_doc(doc_id: str):
    with _store_lock:
        if doc_id not in _store:
            _store[doc_id] = {"metrics": {}, "meta": {}, "samples": []}


def emit(doc_id: str, name: str, value: Any, tags: Optional[Dict[str, str]] = None) -> None:
    """
    Emitir una métrica simple.
    - doc_id: id del documento (sha256:... o similar)
    - name: nombre de la métrica (ej. 'dehyphen_joins')
    - value: número / bool / string / dict
    - tags: metadatos (stage, page, rule)
    """
    _ensure_doc(doc_id)
    entry = {"ts": time.time(), "value": value, "tags": tags or {}}
    with _store_lock:
        metrics = _store[doc_id]["metrics"]
        metrics.setdefault(name, []).append(entry)
    # Log estructurado para visibilidad en stdout/CI
    logger.info(json.dumps({"doc_id": doc_id, "metric": name, "value": value, "tags": tags or {}}))


def set_meta(doc_id: str, key: str, value: Any) -> None:
    """Setear metadata del documento (pages_total, source_filename, pipeline_version, etc)."""
    _ensure_doc(doc_id)
    with _store_lock:
        _store[doc_id]["meta"][key] = value


def add_sample(doc_id: str, sample: Dict[str, Any]) -> None:
    """
    Agregar ejemplo muestreado (before/after) para auditoría.
    sample example: {"page": 3, "rule": "dehyphen", "before": "...", "after":"..."}
    """
    _ensure_doc(doc_id)
    with _store_lock:
        _store[doc_id]["samples"].append({"ts": time.time(), **sample})


@contextmanager
def stage_timer(doc_id: str, stage_name: str):
    """Context manager to measure a stage duration and emit stage status."""
    start = time.time()
    set_meta(doc_id, f"stage_{stage_name}_start", start)
    try:
        yield
        status = "OK"
    except Exception as e:
        status = "FAIL"
        # emit error metric
        emit(doc_id, f"stage.{stage_name}.error", str(e), tags={"stage": stage_name})
        raise
    finally:
        duration = time.time() - start
        emit(doc_id, f"stage.{stage_name}.duration_seconds", duration, tags={"stage": stage_name, "status": status})
        set_meta(doc_id, f"stage_{stage_name}_status", status)


def get_doc_report(doc_id: str) -> Dict[str, Any]:
    """Return the in-memory report dict for the doc."""
    _ensure_doc(doc_id)
    with _store_lock:
        # deep copy-ish (simple)
        data = _store[doc_id].copy()
    return data


def flush_report(doc_id: str, workspace_path: str) -> Path:
    """
    Persistir report JSON a workspace/<doc_id>/report.json (o outputs/reports/ según runner).
    Devuelve la ruta al archivo escrito.
    """
    _ensure_doc(doc_id)
    workspace = Path(workspace_path)
    workspace.mkdir(parents=True, exist_ok=True)
    out_path = workspace / "report.json"
    with _store_lock:
        payload = {
            "doc_id": doc_id,
            "meta": _store[doc_id]["meta"],
            "metrics": _store[doc_id]["metrics"],
            "samples": _store[doc_id]["samples"],
            "generated_at": time.time(),
        }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    logger.info(f"Wrote report {out_path}")
    return out_path
