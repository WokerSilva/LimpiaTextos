# src/limpiatextos/core/errors.py
from __future__ import annotations


class LimpiaTextosError(Exception):
    """Base error for the project."""


class ConfigError(LimpiaTextosError):
    """Raised when configuration is missing/invalid."""


class StageError(LimpiaTextosError):
    """Raised when a stage fails in a controlled way."""


class ArtifactError(LimpiaTextosError):
    """Raised when an artifact is missing/invalid/corrupted."""


class ValidationError(LimpiaTextosError):
    """Raised when QA/validation determines the document is not acceptable."""
