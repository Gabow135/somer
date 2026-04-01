"""Almacenamiento encriptado de credenciales."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.constants import DEFAULT_CREDENTIALS_DIR
from shared.errors import SecretDecryptionError, SecretNotFoundError

logger = logging.getLogger(__name__)

# cryptography es opcional; fallback a obfuscation básica
try:
    from cryptography.fernet import Fernet, InvalidToken

    _HAS_FERNET = True
except ImportError:
    _HAS_FERNET = False
    InvalidToken = Exception  # type: ignore[misc,assignment]


class CredentialStore:
    """Almacenamiento encriptado de credenciales en disco.

    Cada credencial se guarda como un archivo individual en
    ~/.somer/credentials/<service>.enc (encriptado) o
    ~/.somer/credentials/<service>.json (fallback sin fernet).
    """

    def __init__(
        self,
        credentials_dir: Optional[Path] = None,
        encryption_key: Optional[str] = None,
    ):
        self._dir = credentials_dir or DEFAULT_CREDENTIALS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._fernet = None

        if encryption_key and _HAS_FERNET:
            self._fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
        elif _HAS_FERNET:
            self._fernet = self._load_or_create_key()

    def _load_or_create_key(self) -> Optional[Any]:
        """Carga o genera la clave de encriptación."""
        key_file = self._dir / ".key"
        if key_file.exists():
            key = key_file.read_bytes()
        else:
            key = Fernet.generate_key()
            key_file.write_bytes(key)
            key_file.chmod(0o600)
            logger.info("Clave de encriptación generada en %s", key_file)
        return Fernet(key)

    def store(self, service: str, credentials: Dict[str, Any]) -> None:
        """Almacena credenciales para un servicio.

        Args:
            service: Nombre del servicio (ej: "anthropic", "telegram").
            credentials: Dict con las credenciales.
        """
        data = json.dumps(credentials, ensure_ascii=False).encode("utf-8")

        if self._fernet:
            encrypted = self._fernet.encrypt(data)
            path = self._dir / f"{service}.enc"
            path.write_bytes(encrypted)
            path.chmod(0o600)
        else:
            path = self._dir / f"{service}.json"
            path.write_bytes(data)
            path.chmod(0o600)

        logger.info("Credenciales almacenadas para %s", service)

    def retrieve(self, service: str) -> Dict[str, Any]:
        """Recupera credenciales de un servicio.

        Args:
            service: Nombre del servicio.

        Returns:
            Dict con las credenciales.

        Raises:
            SecretNotFoundError: Si no hay credenciales para ese servicio.
            SecretDecryptionError: Si no se pueden descifrar.
        """
        enc_path = self._dir / f"{service}.enc"
        json_path = self._dir / f"{service}.json"

        if enc_path.exists():
            if not self._fernet:
                raise SecretDecryptionError(
                    f"Credenciales de {service} están encriptadas pero "
                    "no hay clave de encriptación disponible"
                )
            try:
                encrypted = enc_path.read_bytes()
                data = self._fernet.decrypt(encrypted)
                return json.loads(data)
            except InvalidToken as exc:
                raise SecretDecryptionError(
                    f"No se pudieron descifrar credenciales de {service}"
                ) from exc
        elif json_path.exists():
            data = json_path.read_bytes()
            return json.loads(data)
        else:
            raise SecretNotFoundError(
                f"No hay credenciales almacenadas para {service}"
            )

    def delete(self, service: str) -> bool:
        """Elimina credenciales de un servicio.

        Returns:
            True si se eliminaron, False si no existían.
        """
        for ext in (".enc", ".json"):
            path = self._dir / f"{service}{ext}"
            if path.exists():
                path.unlink()
                logger.info("Credenciales eliminadas para %s", service)
                return True
        return False

    def list_services(self) -> List[str]:
        """Lista todos los servicios con credenciales almacenadas."""
        services = set()
        for path in self._dir.iterdir():
            if path.suffix in (".enc", ".json") and not path.name.startswith("."):
                services.add(path.stem)
        return sorted(services)

    def has(self, service: str) -> bool:
        """Verifica si hay credenciales para un servicio."""
        enc_path = self._dir / f"{service}.enc"
        json_path = self._dir / f"{service}.json"
        return enc_path.exists() or json_path.exists()
