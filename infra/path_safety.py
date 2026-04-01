"""Protección contra traversal de paths — SOMER.

Portado de OpenClaw: path-safety.ts, boundary-path.ts.

Proporciona validación de paths para prevenir ataques de
path traversal y escape de boundaries de seguridad.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class PathEscapeError(Exception):
    """Error cuando un path intenta escapar de su boundary."""


class PathSafetyValidator:
    """Validador de seguridad de paths.

    Verifica que los paths no escapen del directorio raíz
    permitido, incluyendo resolución de symlinks.
    """

    def __init__(self, root_path: Path, label: str = "boundary") -> None:
        """Inicializa el validador.

        Args:
            root_path: Directorio raíz permitido.
            label: Etiqueta para mensajes de error.
        """
        self._root = root_path.resolve()
        self._label = label

    @property
    def root(self) -> Path:
        """Directorio raíz del boundary."""
        return self._root

    def validate(self, target: Path, resolve_symlinks: bool = True) -> Path:
        """Valida que un path esté dentro del boundary.

        Args:
            target: Path a validar.
            resolve_symlinks: Si resolver symlinks antes de validar.

        Returns:
            Path resuelto y validado.

        Raises:
            PathEscapeError: Si el path escapa del boundary.
        """
        resolved = target.resolve() if resolve_symlinks else _normalize_path(target)

        if not is_path_inside(self._root, resolved):
            raise PathEscapeError(
                f"Path escapa del {self._label} "
                f"({_short_path(self._root)}): "
                f"{_short_path(target)}"
            )

        return resolved

    def validate_relative(self, relative: str) -> Path:
        """Valida un path relativo al boundary.

        Args:
            relative: Path relativo.

        Returns:
            Path absoluto validado.

        Raises:
            PathEscapeError: Si el path escapa del boundary.
        """
        # Verificación léxica rápida
        if ".." in relative.split(os.sep):
            # No rechazar aún — podría resolver correctamente
            pass

        absolute = self._root / relative
        return self.validate(absolute)

    def is_safe(self, target: Path, resolve_symlinks: bool = True) -> bool:
        """Verifica si un path es seguro sin lanzar excepción.

        Args:
            target: Path a verificar.
            resolve_symlinks: Si resolver symlinks.

        Returns:
            True si el path está dentro del boundary.
        """
        try:
            self.validate(target, resolve_symlinks)
            return True
        except (PathEscapeError, OSError):
            return False


def is_path_inside(root: Path, candidate: Path) -> bool:
    """Verifica si un path está dentro de un directorio raíz.

    Ambos paths se resuelven para manejar symlinks y normalización.

    Args:
        root: Directorio raíz.
        candidate: Path candidato.

    Returns:
        True si candidate está dentro (o es igual) a root.
    """
    try:
        root_resolved = root.resolve()
        candidate_resolved = candidate.resolve()
    except OSError:
        # Si no se puede resolver, hacer comparación léxica
        root_resolved = _normalize_path(root)
        candidate_resolved = _normalize_path(candidate)

    # Verificar que el candidato comienza con la raíz
    try:
        candidate_resolved.relative_to(root_resolved)
        return True
    except ValueError:
        return False


def safe_join(root: Path, *parts: str) -> Path:
    """Une paths de forma segura, verificando que no escape.

    Args:
        root: Directorio raíz.
        *parts: Componentes del path a unir.

    Returns:
        Path resultante.

    Raises:
        PathEscapeError: Si el resultado escapa del root.
    """
    result = root
    for part in parts:
        # Rechazar componentes absolutos
        if os.path.isabs(part):
            raise PathEscapeError(
                f"Componente absoluto en safe_join: {part}"
            )
        result = result / part

    resolved = result.resolve()
    root_resolved = root.resolve()

    if not is_path_inside(root_resolved, resolved):
        raise PathEscapeError(
            f"Path escapa de {_short_path(root)}: "
            f"{_short_path(result)}"
        )

    return resolved


def sanitize_filename(name: str, max_length: int = 255) -> str:
    """Sanitiza un nombre de archivo removiendo caracteres peligrosos.

    Args:
        name: Nombre de archivo original.
        max_length: Longitud máxima permitida.

    Returns:
        Nombre sanitizado.
    """
    if not name:
        return "unnamed"

    # Remover caracteres peligrosos
    dangerous = set('/\\:*?"<>|' + "\0")
    sanitized = "".join(c if c not in dangerous else "_" for c in name)

    # Prevenir nombres especiales en Windows
    windows_reserved = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4",
        "LPT1", "LPT2", "LPT3", "LPT4",
    }
    upper = sanitized.upper().split(".")[0]
    if upper in windows_reserved:
        sanitized = f"_{sanitized}"

    # No empezar con punto o guión
    while sanitized and sanitized[0] in (".", "-"):
        sanitized = sanitized[1:]

    if not sanitized:
        return "unnamed"

    # Truncar
    return sanitized[:max_length]


def resolve_path_via_existing_ancestor(target_path: Path) -> Path:
    """Resuelve un path a través de su ancestro existente más cercano.

    Si el path no existe, sube por el árbol hasta encontrar un
    ancestro que exista, lo resuelve (realpath) y le agrega
    los segmentos faltantes.

    Args:
        target_path: Path a resolver.

    Returns:
        Path resuelto lo más fielmente posible.
    """
    normalized = target_path.resolve() if target_path.exists() else Path(os.path.abspath(str(target_path)))

    cursor = normalized
    missing_suffix: list = []

    while cursor != cursor.parent and not cursor.exists():
        missing_suffix.insert(0, cursor.name)
        cursor = cursor.parent

    if not cursor.exists():
        return normalized

    try:
        resolved_ancestor = cursor.resolve()
        if not missing_suffix:
            return resolved_ancestor
        result = resolved_ancestor
        for part in missing_suffix:
            result = result / part
        return result
    except OSError:
        return normalized


def _normalize_path(p: Path) -> Path:
    """Normaliza un path sin resolver symlinks."""
    return Path(os.path.normpath(str(p)))


def _short_path(p: Path) -> str:
    """Acorta un path reemplazando home con ~."""
    home = Path.home()
    try:
        relative = p.relative_to(home)
        return f"~/{relative}"
    except ValueError:
        return str(p)
