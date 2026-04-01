"""SecretRef — Referencias a secretos desde múltiples fuentes.

Portado de OpenClaw: resolve.ts, ref-contract.ts, secret-value.ts.
Incluye resolución síncrona y asíncrona, soporte para keychain macOS,
y validación de valores resueltos.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import subprocess
import logging
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from pydantic import BaseModel

from shared.errors import SecretRefResolutionError

logger = logging.getLogger(__name__)

# ── Constantes de resolución ────────────────────────────────
DEFAULT_EXEC_TIMEOUT_SECS = 5
DEFAULT_FILE_MAX_BYTES = 1024 * 1024
EXEC_SECRET_REF_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
SECRET_PROVIDER_ALIAS_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class SecretSource(str, Enum):
    """Fuentes posibles para un secreto."""
    ENV = "env"
    FILE = "file"
    EXEC = "exec"
    KEYCHAIN = "keychain"
    LITERAL = "literal"  # Solo para testing


class SecretExpectedValue(str, Enum):
    """Tipo esperado del valor resuelto."""
    STRING = "string"
    STRING_OR_OBJECT = "string-or-object"


class SecretRef(BaseModel):
    """Referencia a un secreto que puede venir de env, archivo, comando o keychain.

    Portado de OpenClaw: config/types.secrets.ts SecretRef.
    """

    source: SecretSource
    key: str  # env var name, file path, command, o keychain service
    provider: str = "default"  # Alias del provider de secretos

    def resolve(self) -> str:
        """Resuelve la referencia de forma síncrona y retorna el valor del secreto.

        Returns:
            El valor del secreto.

        Raises:
            SecretRefResolutionError: Si no se puede resolver.
        """
        if self.source == SecretSource.ENV:
            return self._resolve_env()
        elif self.source == SecretSource.FILE:
            return self._resolve_file()
        elif self.source == SecretSource.EXEC:
            return self._resolve_exec()
        elif self.source == SecretSource.KEYCHAIN:
            return self._resolve_keychain()
        elif self.source == SecretSource.LITERAL:
            return self.key
        else:
            raise SecretRefResolutionError(f"Source desconocido: {self.source}")

    async def aresolve(self) -> str:
        """Resuelve la referencia de forma asíncrona.

        Para fuentes env/literal la resolución es inmediata.
        Para file/exec/keychain se ejecuta en un thread pool.

        Returns:
            El valor del secreto.

        Raises:
            SecretRefResolutionError: Si no se puede resolver.
        """
        if self.source in (SecretSource.ENV, SecretSource.LITERAL):
            return self.resolve()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.resolve)

    def ref_key(self) -> str:
        """Genera una clave única para esta referencia.

        Portado de OpenClaw: ref-contract.ts secretRefKey().
        """
        return f"{self.source.value}:{self.provider}:{self.key}"

    def _resolve_env(self) -> str:
        """Resuelve secreto desde variable de entorno."""
        value = os.environ.get(self.key)
        if value is None:
            raise SecretRefResolutionError(
                f"Variable de entorno '{self.key}' no definida"
            )
        return value

    def _resolve_file(self) -> str:
        """Resuelve secreto desde archivo.

        Portado de OpenClaw: resolve.ts readFileProviderPayload() / resolveFileRefs().
        Soporta modo single-value (texto plano) y JSON.
        """
        try:
            path = Path(self.key).expanduser()
            if not path.exists():
                raise SecretRefResolutionError(
                    f"Archivo de secreto no encontrado: {self.key}"
                )
            stat = path.stat()
            if stat.st_size > DEFAULT_FILE_MAX_BYTES:
                raise SecretRefResolutionError(
                    f"Archivo de secreto excede tamaño máximo "
                    f"({stat.st_size} > {DEFAULT_FILE_MAX_BYTES} bytes): {self.key}"
                )
            content = path.read_text(encoding="utf-8").strip()
            # Intentar extraer valor de JSON si la key tiene formato de pointer
            if "/" in self.key:
                # El key puede ser "path/to/file:/json/pointer"
                pass
            return content
        except SecretRefResolutionError:
            raise
        except Exception as exc:
            raise SecretRefResolutionError(
                f"Error leyendo archivo de secreto '{self.key}': {exc}"
            ) from exc

    def _resolve_exec(self) -> str:
        """Resuelve secreto ejecutando un comando.

        Portado de OpenClaw: resolve.ts runExecResolver() / resolveExecRefs().
        """
        try:
            result = subprocess.run(
                self.key,
                shell=True,
                capture_output=True,
                text=True,
                timeout=DEFAULT_EXEC_TIMEOUT_SECS,
            )
            if result.returncode != 0:
                raise SecretRefResolutionError(
                    f"Comando falló (exit {result.returncode}): {result.stderr.strip()}"
                )
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            raise SecretRefResolutionError(
                f"Timeout ejecutando comando de secreto: {self.key}"
            )
        except SecretRefResolutionError:
            raise
        except Exception as exc:
            raise SecretRefResolutionError(
                f"Error ejecutando comando de secreto: {exc}"
            ) from exc

    def _resolve_keychain(self) -> str:
        """Resuelve secreto desde el keychain del sistema operativo.

        En macOS usa 'security find-generic-password'.
        En otros sistemas lanza error indicando que no está soportado.
        """
        if platform.system() != "Darwin":
            raise SecretRefResolutionError(
                "Keychain solo está soportado en macOS"
            )
        try:
            result = subprocess.run(
                [
                    "security", "find-generic-password",
                    "-s", self.key,
                    "-a", "somer",
                    "-w",
                ],
                capture_output=True,
                text=True,
                timeout=DEFAULT_EXEC_TIMEOUT_SECS,
            )
            if result.returncode != 0:
                raise SecretRefResolutionError(
                    f"No se encontró secreto en keychain para servicio '{self.key}'"
                )
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            raise SecretRefResolutionError(
                f"Timeout accediendo al keychain para '{self.key}'"
            )
        except SecretRefResolutionError:
            raise
        except Exception as exc:
            raise SecretRefResolutionError(
                f"Error accediendo al keychain: {exc}"
            ) from exc

    # ── Factory methods ─────────────────────────────────────

    @classmethod
    def from_env(cls, var_name: str, provider: str = "default") -> "SecretRef":
        """Crea referencia a variable de entorno."""
        return cls(source=SecretSource.ENV, key=var_name, provider=provider)

    @classmethod
    def from_file(cls, path: str, provider: str = "default") -> "SecretRef":
        """Crea referencia a archivo."""
        return cls(source=SecretSource.FILE, key=path, provider=provider)

    @classmethod
    def from_exec(cls, command: str, provider: str = "default") -> "SecretRef":
        """Crea referencia a comando."""
        return cls(source=SecretSource.EXEC, key=command, provider=provider)

    @classmethod
    def from_keychain(cls, service: str) -> "SecretRef":
        """Crea referencia a keychain del sistema."""
        return cls(source=SecretSource.KEYCHAIN, key=service, provider="keychain")

    @classmethod
    def literal(cls, value: str) -> "SecretRef":
        """Crea referencia literal (solo para testing)."""
        return cls(source=SecretSource.LITERAL, key=value, provider="literal")

    @classmethod
    def parse_ref_string(cls, value: str) -> Optional["SecretRef"]:
        """Parsea una cadena con formato 'source:provider:id' a SecretRef.

        Portado de OpenClaw: config/types.secrets.ts coerceSecretRef().

        Formatos soportados:
        - "env:default:ANTHROPIC_API_KEY" → SecretRef(env, ANTHROPIC_API_KEY)
        - "$ANTHROPIC_API_KEY" → SecretRef(env, ANTHROPIC_API_KEY, default)
        - "file:/path/to/secret" → SecretRef(file, /path/to/secret, default)
        - "exec:vault:get-key" → SecretRef(exec, get-key, vault)
        - "keychain:somer-anthropic" → SecretRef(keychain, somer-anthropic)

        Returns:
            SecretRef si se pudo parsear, None si no.
        """
        if not isinstance(value, str) or not value.strip():
            return None

        value = value.strip()

        # Atajo: $ENV_VAR
        if value.startswith("$"):
            var_name = value[1:]
            if var_name:
                return cls.from_env(var_name)
            return None

        # Formato completo: source:provider:id
        parts = value.split(":", 2)
        if len(parts) >= 2:
            source_str = parts[0].lower()
            if source_str == "env":
                if len(parts) == 3:
                    return cls.from_env(parts[2], provider=parts[1])
                return cls.from_env(parts[1])
            elif source_str == "file":
                if len(parts) == 3:
                    return cls.from_file(parts[2], provider=parts[1])
                return cls.from_file(parts[1])
            elif source_str == "exec":
                if len(parts) == 3:
                    return cls.from_exec(parts[2], provider=parts[1])
                return cls.from_exec(parts[1])
            elif source_str == "keychain":
                return cls.from_keychain(parts[1])
            elif source_str == "literal":
                rest = ":".join(parts[1:])
                return cls.literal(rest)

        return None


# ── Resolución en lote ──────────────────────────────────────

class SecretResolveCache:
    """Caché de resolución de secretos para evitar resolver múltiples veces.

    Portado de OpenClaw: resolve.ts SecretRefResolveCache.
    """

    def __init__(self) -> None:
        self._resolved: Dict[str, str] = {}

    def get(self, ref: SecretRef) -> Optional[str]:
        """Obtiene valor cacheado para una referencia."""
        return self._resolved.get(ref.ref_key())

    def put(self, ref: SecretRef, value: str) -> None:
        """Cachea el valor resuelto de una referencia."""
        self._resolved[ref.ref_key()] = value

    def has(self, ref: SecretRef) -> bool:
        """Verifica si hay un valor cacheado."""
        return ref.ref_key() in self._resolved

    def clear(self) -> None:
        """Limpia el caché."""
        self._resolved.clear()


async def resolve_refs_batch(
    refs: List[SecretRef],
    cache: Optional[SecretResolveCache] = None,
    max_concurrency: int = 4,
) -> Dict[str, str]:
    """Resuelve múltiples SecretRefs en paralelo con límite de concurrencia.

    Portado de OpenClaw: resolve.ts resolveSecretRefValues().

    Args:
        refs: Lista de SecretRefs a resolver.
        cache: Caché opcional para evitar re-resoluciones.
        max_concurrency: Máximo de resoluciones concurrentes.

    Returns:
        Dict mapeando ref_key → valor resuelto.

    Raises:
        SecretRefResolutionError: Si alguna referencia falla.
    """
    if not refs:
        return {}

    cache = cache or SecretResolveCache()
    semaphore = asyncio.Semaphore(max_concurrency)
    results: Dict[str, str] = {}

    # Deduplicar por ref_key
    unique_refs: Dict[str, SecretRef] = {}
    for ref in refs:
        key = ref.ref_key()
        if cache.has(ref):
            cached = cache.get(ref)
            if cached is not None:
                results[key] = cached
        elif key not in unique_refs:
            unique_refs[key] = ref

    async def _resolve_one(ref: SecretRef) -> None:
        async with semaphore:
            value = await ref.aresolve()
            cache.put(ref, value)
            results[ref.ref_key()] = value

    tasks = [_resolve_one(ref) for ref in unique_refs.values()]
    await asyncio.gather(*tasks)

    return results


# ── Validación de IDs de referencia ─────────────────────────

def is_valid_exec_ref_id(ref_id: str) -> bool:
    """Valida que un ID de referencia exec sea seguro.

    Portado de OpenClaw: ref-contract.ts isValidExecSecretRefId().
    """
    if not EXEC_SECRET_REF_ID_PATTERN.match(ref_id):
        return False
    for segment in ref_id.split("/"):
        if segment in (".", ".."):
            return False
    return True


def is_valid_provider_alias(alias: str) -> bool:
    """Valida que un alias de provider de secretos sea válido.

    Portado de OpenClaw: ref-contract.ts isValidSecretProviderAlias().
    """
    return bool(SECRET_PROVIDER_ALIAS_PATTERN.match(alias))


def is_expected_resolved_value(
    value: Any,
    expected: SecretExpectedValue,
) -> bool:
    """Verifica que el valor resuelto sea del tipo esperado.

    Portado de OpenClaw: secret-value.ts isExpectedResolvedSecretValue().
    """
    if expected == SecretExpectedValue.STRING:
        return isinstance(value, str) and len(value.strip()) > 0
    # STRING_OR_OBJECT
    if isinstance(value, str) and len(value.strip()) > 0:
        return True
    if isinstance(value, dict) and len(value) > 0:
        return True
    return False
