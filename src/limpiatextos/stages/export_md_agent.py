from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, List

import yaml

from limpiatextos.pipeline.registry import stage
from limpiatextos.core.models import Document


@stage(name="export_md_agent", order=900)
class ExportMarkdownForAgent:
    """
    Renderiza un Markdown cognitivo optimizado para agentes,
    usando reglas de structure_mapping.yaml.
    """

    def run(self, doc: Document, ctx) -> Document:
        rules = self._load_structure_rules(ctx)

        # --- 1) Construir YAML front-matter ---
        front_matter = self._build_front_matter(doc, rules)

        # --- 2) Renderizar cuerpo ---
        body_parts: List[str] = []

        for section in doc.sections:  # asumimos sections estructuradas
            if not self._include_section(section, rules):
                continue

            rendered = self._render_section(section, rules)
            if rendered:
                body_parts.append(rendered)

        # --- 3) Ensamblar MD final ---
        md_text = self._assemble_md(front_matter, body_parts)

        # --- 4) Escribir salida ---
        out_dir = Path(ctx.outputs_root) / "md"
        out_dir.mkdir(parents=True, exist_ok=True)

        md_path = out_dir / f"{doc.doc_id}.md"
        md_path.write_text(md_text, encoding="utf-8")

        return doc

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    def _load_structure_rules(self, ctx) -> Dict[str, Any]:
        rules_path = (
            Path(ctx.config.get("_path", "")).parent
            / "strategies"
            / "agent_corpus"
            / "rules"
            / "structure_mapping.yaml"
        )

        if not rules_path.exists():
            raise FileNotFoundError(f"structure_mapping.yaml no encontrado: {rules_path}")

        return yaml.safe_load(rules_path.read_text(encoding="utf-8"))

    def _build_front_matter(self, doc: Document, rules: Dict[str, Any]) -> Dict[str, Any]:
        meta = doc.metadata or {}

        front = {
            "doc_code": meta.get("doc_code"),
            "doc_title": meta.get("doc_title"),
            "doc_subtitle": meta.get("doc_subtitle"),
            "doc_type": meta.get("doc_type"),
            "version": meta.get("version"),
            "publication_date": meta.get("publication_date"),
            "raw_date": meta.get("raw_date"),
            "owner_area": meta.get("owner_area"),
            "classification": meta.get("classification"),
            "source_pdf": Path(doc.source_path).name,
            "generator": "limpiatextos.agent_corpus.v1",
        }

        return {k: v for k, v in front.items() if v is not None}

    def _include_section(self, section: Dict[str, Any], rules: Dict[str, Any]) -> bool:
        section_type = section.get("type")
        section_rules = rules["sections"].get(section_type, {})
        return section_rules.get("include_in_md", False)

    def _render_section(self, section: Dict[str, Any], rules: Dict[str, Any]) -> str:
        section_type = section.get("type")
        title = section.get("title", "")
        content = section.get("content", "")

        if section_type == "bitacora_cambios":
            return self._render_table_section(title, section)

        if section_type == "firmas":
            return self._render_table_section(title, section)

        if section_type == "imagenes":
            return self._render_image_placeholder(section)

        if section_type == "diagramas_flujo":
            return self._render_diagram_card(section)

        # default: texto estructurado
        return f"\n## {title}\n\n{content}\n"

    def _render_table_section(self, title: str, section: Dict[str, Any]) -> str:
        table_md = section.get("table_md")
        if not table_md:
            return ""
        return f"\n## {title}\n\n{table_md}\n"

    def _render_image_placeholder(self, section: Dict[str, Any]) -> str:
        page = section.get("page")
        text = section.get("transcription", "Texto no legible")

        return (
            f"\n> 📷 Imagen detectada (página {page})\n"
            f"> Texto transcrito desde imagen: \"{text}\"\n"
            f"> *Fuente: imagen del documento original*\n"
        )

    def _render_diagram_card(self, section: Dict[str, Any]) -> str:
        title = section.get("title", "Diagrama de flujo")
        desc = section.get("description", "Sin descripción")

        return (
            f"\n> 🔁 Diagrama de flujo detectado: {title}\n"
            f"> Representa: {desc}\n"
        )

    def _assemble_md(self, front_matter: Dict[str, Any], body_parts: List[str]) -> str:
        yaml_block = yaml.safe_dump(front_matter, allow_unicode=True, sort_keys=False)

        md = (
            "---\n"
            f"{yaml_block}"
            "---\n\n"
            + "\n".join(body_parts)
        )

        return md
