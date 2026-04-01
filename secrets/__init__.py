"""Sistema de secretos de SOMER 2.0.

Portado de OpenClaw: src/secrets/.
Proporciona almacenamiento encriptado, resolución multi-fuente,
recolección de secretos requeridos, validación y rotación.

Módulos:
    store:      CredentialStore — almacenamiento encriptado en disco.
    refs:       SecretRef — referencia multi-fuente (env, file, exec, keychain).
    resolve:    Motor de resolución runtime con snapshots.
    collectors: Recolectores de secretos desde config (providers, canales, etc.).
    validation: Validación de formato y conectividad.
    rotation:   Rotación segura de credenciales con backup.
    apply:      Inyección de secretos al runtime/entorno.

NOTA: Este paquete hace shadow al módulo ``secrets`` de la stdlib.
Re-exportamos los atributos de la stdlib para que dependencias externas
(websockets, cryptography, ssl) sigan funcionando correctamente.
"""

from __future__ import annotations

import importlib.util as _importlib_util
import os as _os
import sysconfig as _sysconfig
import types as _types

# Cargar stdlib secrets.py directamente por path (evita recursión)
_stdlib_dir = _sysconfig.get_paths()["stdlib"]
_stdlib_secrets_path = _os.path.join(_stdlib_dir, "secrets.py")
_spec = _importlib_util.spec_from_file_location(
    "stdlib_secrets", _stdlib_secrets_path
)
_stdlib_secrets: _types.ModuleType = _importlib_util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_stdlib_secrets)  # type: ignore[union-attr]

# Re-exportar atributos de la stdlib
token_bytes = _stdlib_secrets.token_bytes
token_hex = _stdlib_secrets.token_hex
token_urlsafe = _stdlib_secrets.token_urlsafe
randbelow = _stdlib_secrets.randbelow
choice = _stdlib_secrets.choice
compare_digest = _stdlib_secrets.compare_digest
SystemRandom = _stdlib_secrets.SystemRandom
