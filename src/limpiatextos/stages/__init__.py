# src/limpiatextos/stages/__init__.py
# Importar módulos para ejecutar los decoradores @stage(...) y registrar en REGISTRY

from . import ingest  # noqa: F401
from . import diagnose  # noqa: F401
from . import ocr  # noqa: F401  # si existe
from . import extract_text  # noqa: F401
from . import extract_tables  # noqa: F401  # si existe
from . import clean  # noqa: F401
from . import nlp  # noqa: F401
from . import chunk  # noqa: F401  # si lo mantienes (aunque deshabilitado)
from . import export  # noqa: F401
from . import validate  # noqa: F401
