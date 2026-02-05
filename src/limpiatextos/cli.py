from limpiatextos.strategies.agent_corpus.runner import AgentCorpusRunner
def handle_agent_corpus(args):
    batch_dir = Path(args.batch_dir).resolve()

    if not batch_dir.exists():
        raise SystemExit(f"[ERROR] Batch no existe: {batch_dir}")

    outputs_dir = Path("outputs/agent_corpus").resolve()

    runner = AgentCorpusRunner(
        batch_dir=batch_dir,
        outputs_dir=outputs_dir,
    )

    runner.run()
# src/limpiatextos/cli.py

import argparse
from pathlib import Path
from typing import Any, Dict, Optional

from limpiatextos.pipeline.runner import run_document


def _parse_stage_overrides(disable: list[str], enable: list[str]) -> Dict[str, Dict[str, Any]]:
    ov: Dict[str, Dict[str, Any]] = {}
    for s in disable:
        ov.setdefault(s, {})["enabled"] = False
    for s in enable:
        ov.setdefault(s, {})["enabled"] = True
    return ov


def cmd_run(args: argparse.Namespace) -> int:
    stage_overrides = _parse_stage_overrides(args.disable_stage or [], args.enable_stage or [])

    res = run_document(
        args.pdf,
        profile=args.profile,
        workspace_root=args.workspace,
        outputs_root=args.outputs,
        configs_dir=args.configs,
        include_stages=args.include_stage,
        exclude_stages=args.exclude_stage,
        stage_overrides=stage_overrides if stage_overrides else None,
        run_id=args.run_id,
    )

    print("doc_id:", res.doc_id)
    print("status:", res.status)
    print("workspace:", res.workspace_doc_dir)
    print("manifest:", res.manifest_path)
    print("report:", res.report_path)

    # ubicaciones principales
    print("outputs/md:", str(Path(args.outputs) / "md" / f"{res.doc_id}.md"))
    print("outputs/text:", str(Path(args.outputs) / "text" / f"{res.doc_id}.txt"))
    print("outputs/jsonl:", str(Path(args.outputs) / "jsonl" / f"{res.doc_id}.jsonl"))
    print("outputs/reports:", str(Path(args.outputs) / "reports" / f"{res.doc_id}.json"))

    return 0 if res.status == "OK" else 2


def cmd_summary(args: argparse.Namespace) -> int:
    # Import local para no cargar dependencias si no se usa
    from tools.generate_summary_csv import generate_summary

    out = generate_summary(outputs_dir=Path(args.outputs), configs_dir=Path(args.configs))
    print(f"Wrote {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="limpiatextos")
    sub = p.add_subparsers(dest="cmd", required=True)
    agent_parser = sub.add_parser(
        "agent-corpus",
        help="Genera un corpus Markdown para carga directa en agentes (por lote)",
    )
    agent_parser.add_argument(
        "batch_dir",
        help="Ruta al lote (ej: input_batches/lote_01)",
    )
    agent_parser.set_defaults(func=handle_agent_corpus)

    runp = sub.add_parser("run", help="Procesa un PDF y genera outputs (md/txt/jsonl/report).")
    runp.add_argument("pdf", help="Ruta al PDF (ej. input_pdfs/doc.pdf)")
    runp.add_argument("--profile", default="default", help="Perfil de config (default/codespaces/high_accuracy)")
    runp.add_argument("--configs", default="configs", help="Directorio de configs/")
    runp.add_argument("--workspace", default="workspace", help="Directorio workspace/")
    runp.add_argument("--outputs", default="outputs", help="Directorio outputs/")
    runp.add_argument("--run-id", default="cli", help="ID de ejecución (trazabilidad)")

    runp.add_argument("--include-stage", action="append", default=None, help="Ejecutar solo estos stages (se puede repetir)")
    runp.add_argument("--exclude-stage", action="append", default=None, help="Excluir estos stages (se puede repetir)")
    runp.add_argument("--disable-stage", action="append", default=None, help="Deshabilitar stage (override) (se puede repetir)")
    runp.add_argument("--enable-stage", action="append", default=None, help="Habilitar stage (override) (se puede repetir)")

    runp.set_defaults(func=cmd_run)

    sump = sub.add_parser("summary", help="Genera outputs/reports/summary.csv a partir de reports/*.json")
    sump.add_argument("--outputs", default="outputs", help="Directorio outputs/")
    sump.add_argument("--configs", default="configs", help="Directorio configs/")
    sump.set_defaults(func=cmd_summary)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
