# src/limpiatextos/pipeline/registry.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from src.limpiatextos.pipeline.stages import Stage, StageSpec


class StageRegistry:
    """
    Registro de stages por nombre.
    Permite:
    - registrar stages base
    - habilitar/deshabilitar por config
    - ordenar para construir un pipeline lineal (DAG simple)
    """
    def __init__(self) -> None:
        self._specs: Dict[str, StageSpec] = {}

    def register(self, spec: StageSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"Stage already registered: {spec.name}")
        self._specs[spec.name] = spec

    def unregister(self, name: str) -> None:
        self._specs.pop(name, None)

    def get_spec(self, name: str) -> StageSpec:
        if name not in self._specs:
            raise KeyError(f"Stage not found: {name}")
        return self._specs[name]

    def list_specs(self) -> List[StageSpec]:
        return sorted(self._specs.values(), key=lambda s: (s.order, s.name))

    def build_pipeline(
        self,
        include: Optional[Sequence[str]] = None,
        exclude: Optional[Sequence[str]] = None,
        overrides: Optional[Dict[str, Dict]] = None,
    ) -> List[Stage]:
        """
        Construye la lista de stages (instancias) para ejecutar.

        include: si se provee, sólo esos stages (en el orden definido por 'order').
        exclude: lista de nombres a excluir.
        overrides: dict por stage_name para setear enabled/order/tags (no muta factory).
        """
        exclude_set = set(exclude or [])

        specs = {k: v for k, v in self._specs.items()}

        # Apply overrides (sin tocar el original)
        if overrides:
            for name, patch in overrides.items():
                if name not in specs:
                    continue
                base = specs[name]
                specs[name] = StageSpec(
                    name=base.name,
                    factory=base.factory,
                    enabled=bool(patch.get("enabled", base.enabled)),
                    order=int(patch.get("order", base.order)),
                    tags=dict(base.tags) | dict(patch.get("tags", {}) or {}),
                )

        # Filter include/exclude/enabled
        if include is not None:
            include_set = set(include)
            selected = [s for s in specs.values() if s.name in include_set]
        else:
            selected = list(specs.values())

        selected = [s for s in selected if s.enabled and s.name not in exclude_set]
        selected.sort(key=lambda s: (s.order, s.name))

        # Instantiate
        pipeline: List[Stage] = []
        for spec in selected:
            stage = spec.factory()
            pipeline.append(stage)
        return pipeline


# Singleton registry (simple; se puede reemplazar en tests)
REGISTRY = StageRegistry()


def stage(
    name: str,
    *,
    order: int = 0,
    enabled: bool = True,
    tags: Optional[Dict[str, str]] = None,
):
    """
    Decorador para registrar un stage factory.
    Uso:
        @stage("ingest", order=10)
        def make_ingest():
            return IngestStage()
    """
    tags = tags or {}

    def _decorator(factory):
        REGISTRY.register(StageSpec(name=name, factory=factory, enabled=enabled, order=order, tags=tags))
        return factory

    return _decorator
