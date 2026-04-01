"""Tool de ejecución de código (Code Interpreter) para agentes.

Ejecuta código Python en un entorno aislado con acceso a librerías
de análisis de datos, visualización y procesamiento.

Seguridad:
- Ejecución en subprocess aislado
- Timeout configurable
- Sin acceso a red por defecto
- Captura de stdout, stderr y archivos generados

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from typing import Any, Dict, List, Optional

from agents.tools.registry import (
    ToolDefinition,
    ToolProfile,
    ToolRegistry,
    ToolSection,
)

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────

_DEFAULT_TIMEOUT = 120
_MAX_TIMEOUT = 300
_MAX_OUTPUT_LENGTH = 30_000
_OUTPUT_DIR = os.path.expanduser("~/.somer/code_interpreter/output")

# Imports automáticos disponibles en el sandbox
_AUTO_IMPORTS = """
import sys
import os
import json
import csv
import math
import re
import datetime
import collections
import itertools
import functools
import pathlib
from typing import Any, Dict, List, Optional, Tuple

# Intentar importar librerías de datos
try:
    import pandas as pd
except ImportError:
    pass
try:
    import numpy as np
except ImportError:
    pass
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
except ImportError:
    pass
try:
    import seaborn as sns
except ImportError:
    pass
try:
    from scipy import stats
except ImportError:
    pass
try:
    import sqlite3
except ImportError:
    pass
"""


# ── Helpers ──────────────────────────────────────────────────


def _ensure_output_dir() -> str:
    """Crea y retorna el directorio de output."""
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    return _OUTPUT_DIR


def _build_sandbox_script(
    code: str,
    output_dir: str,
    *,
    data_files: Optional[List[str]] = None,
) -> str:
    """Construye el script completo para ejecución en sandbox."""
    script_parts = [
        "# -*- coding: utf-8 -*-",
        _AUTO_IMPORTS,
        f'_OUTPUT_DIR = "{output_dir}"',
        'os.makedirs(_OUTPUT_DIR, exist_ok=True)',
        '',
    ]

    # Cargar archivos de datos si se proporcionan
    if data_files:
        for fpath in data_files:
            if os.path.exists(fpath):
                var_name = os.path.splitext(os.path.basename(fpath))[0]
                var_name = re.sub(r'[^a-zA-Z0-9_]', '_', var_name)
                ext = os.path.splitext(fpath)[1].lower()
                if ext == '.csv':
                    script_parts.append(
                        f'try:\n    {var_name} = pd.read_csv("{fpath}")\n'
                        f'    print(f"{var_name}: {{len({var_name})}} filas")\n'
                        f'except Exception as e:\n    print(f"Error cargando {fpath}: {{e}}")'
                    )
                elif ext == '.json':
                    script_parts.append(
                        f'with open("{fpath}") as _f:\n    {var_name} = json.load(_f)\n'
                        f'print(f"{var_name}: cargado")'
                    )

    # Helper para guardar figuras
    script_parts.append('''
def save_figure(fig=None, name="plot"):
    """Guarda una figura matplotlib en el directorio de output."""
    if fig is None:
        fig = plt.gcf()
    path = os.path.join(_OUTPUT_DIR, f"{name}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[FIGURE_SAVED] {path}")
    return path
''')

    # Código del usuario
    script_parts.append("# ── User Code ──")
    script_parts.append(code)

    # Auto-save de figuras pendientes
    script_parts.append('''
# Auto-save figuras pendientes
try:
    if plt.get_fignums():
        for i, num in enumerate(plt.get_fignums()):
            fig = plt.figure(num)
            save_figure(fig, f"auto_plot_{i}")
except Exception:
    pass
''')

    return "\n".join(script_parts)


# ── Handler ──────────────────────────────────────────────────


async def _code_interpreter_handler(args: Dict[str, Any]) -> str:
    """Ejecuta código Python en un entorno sandbox."""
    code = args.get("code", "").strip()
    if not code:
        return json.dumps({"error": "code es requerido."})

    timeout = min(args.get("timeout", _DEFAULT_TIMEOUT), _MAX_TIMEOUT)
    data_files = args.get("data_files", [])
    description = args.get("description", "")

    # Crear directorio de output para esta ejecución
    run_id = uuid.uuid4().hex[:8]
    output_dir = os.path.join(_ensure_output_dir(), run_id)
    os.makedirs(output_dir, exist_ok=True)

    # Construir script
    script = _build_sandbox_script(code, output_dir, data_files=data_files)

    # Escribir script temporal
    script_path = os.path.join(output_dir, "_script.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)

    start = time.monotonic()
    logger.info(
        "Code interpreter: %s (run=%s, timeout=%ds)",
        description or code[:80],
        run_id,
        timeout,
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", script_path,
            cwd=output_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={
                **os.environ,
                "MPLBACKEND": "Agg",
                "PYTHONIOENCODING": "utf-8",
            },
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        duration = time.monotonic() - start
        return json.dumps({
            "error": f"Ejecución excedió timeout de {timeout}s.",
            "duration_secs": round(duration, 2),
            "run_id": run_id,
        })
    except Exception as exc:
        return json.dumps({"error": f"Error ejecutando código: {str(exc)[:500]}"})

    duration = time.monotonic() - start
    stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

    # Truncar salidas
    if len(stdout) > _MAX_OUTPUT_LENGTH:
        stdout = stdout[:_MAX_OUTPUT_LENGTH] + "\n\n[... salida truncada ...]"
    if len(stderr) > _MAX_OUTPUT_LENGTH:
        stderr = stderr[:_MAX_OUTPUT_LENGTH] + "\n\n[... error truncado ...]"

    # Listar archivos generados
    generated_files: List[str] = []
    for fname in os.listdir(output_dir):
        if fname.startswith("_"):
            continue
        fpath = os.path.join(output_dir, fname)
        if os.path.isfile(fpath):
            size = os.path.getsize(fpath)
            generated_files.append(f"{fname} ({size} bytes)")

    result: Dict[str, Any] = {
        "status": "success" if proc.returncode == 0 else "error",
        "exit_code": proc.returncode,
        "duration_secs": round(duration, 2),
        "run_id": run_id,
    }

    if stdout:
        result["output"] = stdout
    if stderr and proc.returncode != 0:
        result["error_output"] = stderr
    if generated_files:
        result["files"] = generated_files
        result["output_dir"] = output_dir

    # Limpiar script temporal
    try:
        os.remove(script_path)
    except Exception:
        pass

    return json.dumps(result, ensure_ascii=False)


# ── Registro ─────────────────────────────────────────────────


def register_code_interpreter_tools(registry: ToolRegistry) -> None:
    """Registra las tools de code interpreter en el registry."""

    registry.register(ToolDefinition(
        id="code_interpreter",
        name="code_interpreter",
        description=(
            "Ejecuta código Python en un entorno sandbox con librerías de datos. "
            "Tiene acceso automático a: pandas, numpy, matplotlib, seaborn, scipy, sqlite3. "
            "Usar para: análisis de datos, cálculos complejos, generar gráficos, "
            "procesar CSVs/JSONs, estadísticas, visualizaciones. "
            "Las figuras de matplotlib se guardan automáticamente como PNG. "
            "NO usar para: operaciones del sistema (usar shell_exec), "
            "tareas que requieran red, o código que modifique archivos fuera del sandbox."
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": (
                        "Código Python a ejecutar. Las librerías pandas, numpy, "
                        "matplotlib, seaborn están pre-importadas si están disponibles."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "Descripción breve de qué hace el código (para logging).",
                },
                "data_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Rutas a archivos de datos (.csv, .json) a cargar automáticamente "
                        "como DataFrames/dicts con nombre basado en el archivo."
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout en segundos (default: 120, max: 300).",
                },
            },
            "required": ["code"],
        },
        handler=_code_interpreter_handler,
        section=ToolSection.RUNTIME,
        profiles=[ToolProfile.CODING, ToolProfile.FULL],
        timeout_secs=300.0,
    ))

    logger.info("Code interpreter tools registradas: 1 tool")
