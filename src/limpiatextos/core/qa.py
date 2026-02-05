# src/limpiatextos/core/qa.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from limpiatextos.core.errors import ConfigError


@dataclass(frozen=True)
class QAResult:
    overall_flag: str  # OK | REVIEW | FAIL
    reasons: List[Dict[str, Any]]  # [{code, message, metric, value, threshold}, ...]


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception as e:
        raise ConfigError("PyYAML no está instalado. Agrega 'pyyaml' a pyproject.toml.") from e

    if not path.exists():
        raise ConfigError(f"QA thresholds not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_thresholds(configs_dir: str = "configs", filename: str = "qa_thresholds.yaml") -> Dict[str, Any]:
    return _load_yaml(Path(configs_dir) / filename)


def _metric_last(metrics: Dict[str, Any], name: str) -> Optional[Any]:
    """
    logging.emit guarda: metrics[name] = [{ts, value, tags}, ...]
    Tomamos el último valor emitido.
    """
    arr = metrics.get(name)
    if not arr:
        return None
    if isinstance(arr, list) and arr:
        return arr[-1].get("value")
    return None


def _meta_get(meta: Dict[str, Any], key: str, default: Any = None) -> Any:
    return meta.get(key, default)


def _add_reason(reasons: List[Dict[str, Any]], code: str, message: str, **kwargs) -> None:
    reasons.append({"code": code, "message": message, **kwargs})


def compute_overall_flag(doc_report: Dict[str, Any], thresholds: Dict[str, Any]) -> QAResult:
    """
    Evalúa umbrales y retorna OK/REVIEW/FAIL + razones.
    doc_report: estructura retornada por core.logging.get_doc_report(doc_id)
               o la estructura de report.json (con keys: meta, metrics, samples).
    """
    meta = doc_report.get("meta", {}) or {}
    metrics = doc_report.get("metrics", {}) or {}

    reasons: List[Dict[str, Any]] = []
    flag = "OK"

    # ---- Pages / text presence ----
    pages_total = _meta_get(meta, "pages_total", 0) or 0
    pages_with_text = _meta_get(meta, "pages_with_text_count", None)
    pages_empty_ratio = _meta_get(meta, "pages_empty_ratio", None)

    # si meta no lo trae, intentar de métricas
    if pages_with_text is None:
        pages_with_text = _metric_last(metrics, "pages_with_text_count")
    if pages_empty_ratio is None:
        pages_empty_ratio = _metric_last(metrics, "pages_empty_ratio")

    pages_cfg = thresholds.get("pages", {}) or {}
    empty_warn = pages_cfg.get("pages_empty_ratio_warn", 0.1)
    empty_fail = pages_cfg.get("pages_empty_ratio_fail", 0.5)

    if isinstance(pages_empty_ratio, (int, float)):
        if pages_empty_ratio >= empty_fail:
            flag = "FAIL"
            _add_reason(
                reasons,
                code="PAGES_EMPTY_RATIO_FAIL",
                message="Demasiadas páginas vacías/sin texto.",
                metric="pages_empty_ratio",
                value=pages_empty_ratio,
                threshold=empty_fail,
            )
        elif pages_empty_ratio >= empty_warn and flag != "FAIL":
            if flag == "OK":
                flag = "REVIEW"
            _add_reason(
                reasons,
                code="PAGES_EMPTY_RATIO_WARN",
                message="Proporción de páginas vacías alta; revisar OCR/extracción.",
                metric="pages_empty_ratio",
                value=pages_empty_ratio,
                threshold=empty_warn,
            )

    # ---- OCR confidence (si aplica) ----
    ocr_used = _meta_get(meta, "ocr_used", None)
    if ocr_used is None:
        ocr_used = _metric_last(metrics, "ocr_used")

    ocr_cfg = thresholds.get("ocr", {}) or {}
    conf_warn = ocr_cfg.get("ocr_confidence_mean_warn", 0.6)
    conf_fail = ocr_cfg.get("ocr_confidence_mean_fail", 0.4)

    ocr_conf = _meta_get(meta, "ocr_confidence_mean", None)
    if ocr_conf is None:
        ocr_conf = _metric_last(metrics, "ocr_confidence_mean")

    if bool(ocr_used) and isinstance(ocr_conf, (int, float)):
        if ocr_conf < conf_fail:
            flag = "FAIL"
            _add_reason(
                reasons,
                code="OCR_CONFIDENCE_FAIL",
                message="Confianza promedio de OCR demasiado baja.",
                metric="ocr_confidence_mean",
                value=ocr_conf,
                threshold=conf_fail,
            )
        elif ocr_conf < conf_warn and flag != "FAIL":
            if flag == "OK":
                flag = "REVIEW"
            _add_reason(
                reasons,
                code="OCR_CONFIDENCE_WARN",
                message="Confianza promedio de OCR baja; revisar calidad del escaneo/config.",
                metric="ocr_confidence_mean",
                value=ocr_conf,
                threshold=conf_warn,
            )

    # ---- Tables extraction success ratio ----
    tables_cfg = thresholds.get("tables", {}) or {}
    tables_ok = tables_cfg.get("tables_extraction_success_ratio_ok", 0.8)
    tables_warn = tables_cfg.get("tables_extraction_success_ratio_warn", 0.6)

    tables_ratio = _meta_get(meta, "tables_extraction_success_ratio", None)
    if tables_ratio is None:
        tables_ratio = _metric_last(metrics, "tables_extraction_success_ratio")

    if isinstance(tables_ratio, (int, float)):
        if tables_ratio < tables_warn and flag != "FAIL":
            if flag == "OK":
                flag = "REVIEW"
            _add_reason(
                reasons,
                code="TABLES_SUCCESS_RATIO_LOW",
                message="Baja tasa de éxito en extracción de tablas; revisar extractor.",
                metric="tables_extraction_success_ratio",
                value=tables_ratio,
                threshold=tables_warn,
            )
        elif tables_ratio < tables_ok and flag == "OK":
            # leve señal para revisión (opcional)
            flag = "REVIEW"
            _add_reason(
                reasons,
                code="TABLES_SUCCESS_RATIO_MED",
                message="Tasa de éxito de tablas moderada; podría mejorar.",
                metric="tables_extraction_success_ratio",
                value=tables_ratio,
                threshold=tables_ok,
            )

    # ---- Cleaning sanity: line_join_ratio ----
    cleaning_cfg = thresholds.get("cleaning", {}) or {}
    line_cfg = cleaning_cfg.get("line_join", {}) or {}
    lj_min = line_cfg.get("line_join_ratio_min", 0.01)
    lj_max = line_cfg.get("line_join_ratio_max", 0.6)

    line_joins = _meta_get(meta, "line_joins", None)
    if line_joins is None:
        line_joins = _metric_last(metrics, "line_joins")

    chars_clean_total = _meta_get(meta, "chars_clean_total", None)
    if chars_clean_total is None:
        chars_clean_total = _metric_last(metrics, "chars_clean_total")

    # ratio aproximado (joins / max(chars,1)) * 1000 => normalizado
    # (evita requerir contadores detallados por línea en esta fase)
    if isinstance(line_joins, (int, float)) and isinstance(chars_clean_total, (int, float)) and chars_clean_total > 0:
        line_join_ratio = float(line_joins) / float(chars_clean_total)
        if (line_join_ratio < lj_min or line_join_ratio > lj_max) and flag != "FAIL":
            if flag == "OK":
                flag = "REVIEW"
            _add_reason(
                reasons,
                code="LINE_JOIN_RATIO_OUT_OF_RANGE",
                message="La unión de líneas parece fuera de rango (posible under/over-join).",
                metric="line_join_ratio",
                value=line_join_ratio,
                threshold={"min": lj_min, "max": lj_max},
            )
        # guardar para quien consuma
        meta["line_join_ratio"] = line_join_ratio

    return QAResult(overall_flag=flag, reasons=reasons)
