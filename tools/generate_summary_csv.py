# tools/generate_summary_csv.py
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception as e:
        raise RuntimeError("PyYAML no está instalado. Agrega 'pyyaml' a pyproject.toml.") from e

    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def safe_get(d: Dict[str, Any], key: str, default: Any = "") -> Any:
    return d.get(key, default)


def flatten_for_csv(report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza el report JSON para extraer un set simple de campos.
    Intenta tomar de:
      - report["meta"]
      - report["qa"]
      - algunas métricas comunes
    """
    meta = report.get("meta", {}) or {}
    qa = report.get("qa", {}) or {}
    metrics = report.get("metrics", {}) or {}

    def metric_last(name: str) -> Any:
        arr = metrics.get(name)
        if isinstance(arr, list) and arr:
            return arr[-1].get("value", "")
        return ""

    row: Dict[str, Any] = {}

    # Meta común
    row["doc_id"] = safe_get(report, "doc_id", safe_get(meta, "doc_id", ""))
    row["source_filename"] = safe_get(meta, "source_filename", "")
    row["pages_total"] = safe_get(meta, "pages_total", metric_last("pages_total"))
    row["pages_with_text_count"] = safe_get(meta, "pages_with_text_count", metric_last("pages_with_text_count"))
    row["pages_empty_ratio"] = safe_get(meta, "pages_empty_ratio", metric_last("pages_empty_ratio"))

    row["ocr_used"] = safe_get(meta, "ocr_used", metric_last("ocr_used"))
    row["ocr_confidence_mean"] = safe_get(meta, "ocr_confidence_mean", metric_last("ocr_confidence_mean"))

    row["tables_detected_count"] = safe_get(meta, "tables_detected_count", metric_last("tables_detected_count"))
    row["tables_extraction_success_ratio"] = safe_get(
        meta, "tables_extraction_success_ratio", metric_last("tables_extraction_success_ratio")
    )

    row["dehyphen_joins"] = safe_get(meta, "dehyphen_joins", metric_last("dehyphen_joins"))
    row["line_joins"] = safe_get(meta, "line_joins", metric_last("line_joins"))

    row["chunks_count"] = safe_get(meta, "chunks_count", metric_last("chunks_count"))

    # QA
    row["overall_flag"] = safe_get(meta, "overall_flag", safe_get(qa, "overall_flag", ""))
    row["qa_reasons_count"] = len(safe_get(qa, "reasons", []) or [])

    # Tiempos si existen
    row["processing_time_seconds"] = safe_get(meta, "pipeline_duration_seconds", "")

    return row


def resolve_columns(configs_dir: Path) -> List[str]:
    cfg = load_yaml(configs_dir / "qa_thresholds.yaml")
    cols = (((cfg.get("reporting") or {}).get("summary_csv_columns")) or None)
    if isinstance(cols, list) and cols:
        return [str(c) for c in cols]

    # fallback razonable
    return [
        "doc_id",
        "source_filename",
        "pages_total",
        "pages_with_text_count",
        "pages_empty_ratio",
        "ocr_used",
        "ocr_confidence_mean",
        "tables_detected_count",
        "tables_extraction_success_ratio",
        "dehyphen_joins",
        "line_joins",
        "chunks_count",
        "overall_flag",
        "qa_reasons_count",
        "processing_time_seconds",
    ]


def generate_summary(
    outputs_dir: Path = Path("outputs"),
    configs_dir: Path = Path("configs"),
) -> Path:
    reports_dir = outputs_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    out_csv = reports_dir / "summary.csv"
    report_files = sorted(reports_dir.glob("*.json"))

    columns = resolve_columns(configs_dir)

    rows: List[Dict[str, Any]] = []
    for fp in report_files:
        try:
            report = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            # si un json está corrupto, lo saltamos
            continue
        row = flatten_for_csv(report)

        # Asegura todas las columnas
        normalized = {c: row.get(c, "") for c in columns}
        rows.append(normalized)

    # Escribir CSV
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    return out_csv


def main(argv: List[str]) -> int:
    # Uso simple:
    #   python tools/generate_summary_csv.py
    #   python tools/generate_summary_csv.py outputs configs
    outputs_dir = Path(argv[1]) if len(argv) > 1 else Path("outputs")
    configs_dir = Path(argv[2]) if len(argv) > 2 else Path("configs")

    out = generate_summary(outputs_dir=outputs_dir, configs_dir=configs_dir)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
