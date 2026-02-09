from __future__ import annotations

from pathlib import Path
from typing import List

# -------------------------------------------------------------------
# Configuración por defecto
# -------------------------------------------------------------------

DEFAULT_THRESHOLD = 0.98


# -------------------------------------------------------------------
# Core logic
# -------------------------------------------------------------------

def pack_md_for_agents(
    *,
    lote_id: str,
    base_outputs: Path = Path("outputs/agent_corpus"),
    max_size_mb: int = 20,
    threshold: float = DEFAULT_THRESHOLD,
) -> List[Path]:
    """
    Empaqueta archivos .md en bloques grandes, respetando un tamaño máximo
    pensado para subirlos a agentes (ChatGPT, Copilot, Gemini, etc.).

    - Lee los .md desde: outputs/agent_corpus/<lote_id>/md/
    - Genera archivos en: outputs/agent_corpus/<lote_id>/agent_packages/
    - Corta cuando el archivo llega al ~threshold del tamaño máximo
    - Retorna la lista de archivos generados
    """

    md_dir = base_outputs / lote_id / "md"
    if not md_dir.exists():
        raise FileNotFoundError(f"No existe la carpeta de entrada: {md_dir}")

    md_files = sorted(md_dir.glob("*.md"))
    if not md_files:
        raise RuntimeError(f"No hay archivos .md en {md_dir}")

    # tamaño máximo efectivo en bytes
    max_bytes = int(max_size_mb * 1024 * 1024 * threshold)

    out_dir = base_outputs / lote_id / "agent_packages"
    out_dir.mkdir(parents=True, exist_ok=True)

    generated: List[Path] = []

    current_buffer: List[str] = []
    current_size = 0
    package_idx = 1

    def flush() -> None:
        nonlocal package_idx, current_buffer, current_size
        if not current_buffer:
            return

        out_path = out_dir / f"agent_package_{package_idx:03d}.md"
        out_path.write_text("".join(current_buffer), encoding="utf-8")
        generated.append(out_path)

        package_idx += 1
        current_buffer = []
        current_size = 0

    # -------------------------------------------------------------------
    # Empaquetado
    # -------------------------------------------------------------------

    for md_path in md_files:
        content = md_path.read_text(encoding="utf-8")
        content_bytes = len(content.encode("utf-8"))

        header = (
            "\n\n"
            "============================================================\n"
            f"# Documento: {md_path.name}\n"
            "============================================================\n\n"
        )
        header_bytes = len(header.encode("utf-8"))

        block_size = header_bytes + content_bytes

        # Si el bloque no cabe en el archivo actual, cerramos y abrimos otro
        if current_size > 0 and current_size + block_size > max_bytes:
            flush()

        # Si el archivo individual ya es más grande que el máximo,
        # lo dejamos solo en su propio paquete
        if block_size > max_bytes:
            current_buffer.append(header)
            current_buffer.append(content)
            flush()
            continue

        current_buffer.append(header)
        current_buffer.append(content)
        current_size += block_size

    flush()
    return generated
