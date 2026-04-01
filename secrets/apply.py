"""Aplicar secretos al runtime — conecta SecretRef con CredentialStore.

Portado de OpenClaw: runtime.ts + apply.ts.
Proporciona resolución síncrona y asíncrona de secretos,
inyección en el entorno del proceso, y aplicación completa
vía snapshot de secretos.
"""

from __future__ import annotations

import os
import logging
from typing import Any, Dict, List, Optional

from config.schema import SomerConfig
from secrets.refs import SecretRef, SecretSource
from secrets.store import CredentialStore

logger = logging.getLogger(__name__)


def apply_secrets_to_env(
    config: SomerConfig,
    store: Optional[CredentialStore] = None,
) -> Dict[str, str]:
    """Aplica secrets al entorno del proceso.

    Resuelve SecretRefs de providers y canales y los inyecta como
    variables de entorno.

    Args:
        config: Configuración de SOMER.
        store: CredentialStore opcional para buscar credenciales.

    Returns:
        Dict con las env vars que se aplicaron.
    """
    applied: Dict[str, str] = {}

    # Providers
    for provider_id, provider_settings in config.providers.items():
        auth = provider_settings.auth
        if auth.api_key_env and not os.environ.get(auth.api_key_env):
            # Intentar resolver desde store
            value = _try_resolve(provider_id, "api_key", auth.api_key_env, store)
            if value:
                os.environ[auth.api_key_env] = value
                applied[auth.api_key_env] = "***"
                logger.debug("Secret aplicado: %s", auth.api_key_env)

    # Channels
    for channel_id, channel_config in config.channels.entries.items():
        for key, value in channel_config.config.items():
            if isinstance(value, str) and value.startswith("$"):
                env_var = value[1:]
                if not os.environ.get(env_var):
                    resolved = _try_resolve(channel_id, key, env_var, store)
                    if resolved:
                        os.environ[env_var] = resolved
                        applied[env_var] = "***"

    return applied


async def apply_secrets_async(
    config: SomerConfig,
    store: Optional[CredentialStore] = None,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Aplica secrets al entorno de forma asíncrona usando el motor de resolución.

    Portado de OpenClaw: runtime.ts prepareSecretsRuntimeSnapshot() +
    activateSecretsRuntimeSnapshot().

    A diferencia de apply_secrets_to_env(), esta versión:
    - Usa el motor completo de resolución con ResolverContext.
    - Soporta todas las fuentes (env, file, exec, keychain).
    - Resuelve referencias en paralelo con control de concurrencia.
    - Crea un snapshot activable.

    Args:
        config: Configuración de SOMER.
        store: CredentialStore opcional.
        env: Variables de entorno (default: os.environ).

    Returns:
        Dict con las env vars que se aplicaron.
    """
    from secrets.resolve import (
        prepare_secrets_snapshot,
        activate_snapshot,
    )

    snapshot = await prepare_secrets_snapshot(config, env)
    activate_snapshot(snapshot)

    # Aplicar al entorno las env vars que se pudieron resolver
    applied: Dict[str, str] = {}
    for provider_id, provider_settings in snapshot.config.providers.items():
        auth = provider_settings.auth
        if auth.api_key and auth.api_key_env:
            if not os.environ.get(auth.api_key_env):
                os.environ[auth.api_key_env] = auth.api_key
                applied[auth.api_key_env] = "***"

    return applied


def resolve_provider_key(
    provider_id: str,
    config: SomerConfig,
    store: Optional[CredentialStore] = None,
) -> Optional[str]:
    """Resuelve la API key de un provider específico.

    Orden de resolución:
    1. Env var directa
    2. Config literal (solo testing)
    3. CredentialStore
    4. SecretRef (file/exec)
    5. SecretRef string en config (formato $VAR, env:..., file:..., etc.)

    Args:
        provider_id: ID del provider.
        config: Configuración de SOMER.
        store: CredentialStore opcional.

    Returns:
        La API key o None.
    """
    provider = config.providers.get(provider_id)
    if not provider:
        return None

    auth = provider.auth

    # 1. Env var directa
    if auth.api_key_env:
        env_value = os.environ.get(auth.api_key_env)
        if env_value:
            return env_value

    # 2. Literal (testing) o SecretRef string
    if auth.api_key:
        # Intentar parsear como SecretRef
        ref = SecretRef.parse_ref_string(auth.api_key)
        if ref:
            try:
                return ref.resolve()
            except Exception:
                logger.debug(
                    "No se pudo resolver SecretRef para %s: %s",
                    provider_id, auth.api_key,
                )
        else:
            # Es un literal
            return auth.api_key

    # 3. Store
    if store and store.has(provider_id):
        try:
            creds = store.retrieve(provider_id)
            return creds.get("api_key")
        except Exception:
            logger.debug(
                "No se pudieron recuperar credenciales de store para %s",
                provider_id,
            )

    # 4. File ref
    if auth.api_key_file:
        try:
            ref = SecretRef.from_file(auth.api_key_file)
            return ref.resolve()
        except Exception:
            logger.debug("No se pudo resolver file ref para %s", provider_id)

    return None


def resolve_channel_secret(
    channel_id: str,
    field_name: str,
    config: SomerConfig,
    store: Optional[CredentialStore] = None,
) -> Optional[str]:
    """Resuelve un secreto específico de un canal.

    Portado de OpenClaw: runtime-config-collectors-channels.ts
    (resolución de campos individuales de canal).

    Orden de resolución:
    1. Valor literal en config del canal.
    2. SecretRef string en config del canal.
    3. Variable de entorno conocida.
    4. CredentialStore.

    Args:
        channel_id: ID del canal.
        field_name: Nombre del campo (ej: "bot_token").
        config: Configuración de SOMER.
        store: CredentialStore opcional.

    Returns:
        El valor del secreto o None.
    """
    channel = config.channels.entries.get(channel_id)
    if not channel:
        return None

    # 1. Valor en config
    value = channel.config.get(field_name)
    if isinstance(value, str) and value.strip():
        # Intentar como SecretRef
        ref = SecretRef.parse_ref_string(value)
        if ref:
            try:
                return ref.resolve()
            except Exception:
                logger.debug(
                    "No se pudo resolver SecretRef de canal %s.%s",
                    channel_id, field_name,
                )
        else:
            return value

    # 2. Env var conocida
    from secrets.collectors import CHANNEL_REQUIRED_SECRETS
    required = CHANNEL_REQUIRED_SECRETS.get(channel_id, [])
    for spec in required:
        if spec["field"] == field_name:
            env_value = os.environ.get(spec["env"])
            if env_value:
                return env_value

    # 3. Store
    if store and store.has(channel_id):
        try:
            creds = store.retrieve(channel_id)
            return creds.get(field_name)
        except Exception:
            pass

    return None


def scrub_secret_env_vars(
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Elimina env vars que contienen secretos del entorno.

    Portado de OpenClaw: provider-env-vars.ts omitEnvKeysCaseInsensitive().

    Útil para limpiar el entorno antes de pasar a procesos hijos
    que no deben tener acceso a las credenciales.

    Args:
        env: Dict de env vars (default: os.environ).

    Returns:
        Dict de env vars limpio (sin secretos).
    """
    from secrets.collectors import list_known_secret_env_vars

    target = dict(env) if env is not None else dict(os.environ)
    secret_vars = set(v.upper() for v in list_known_secret_env_vars())

    cleaned: Dict[str, str] = {}
    for key, value in target.items():
        if key.upper() not in secret_vars:
            cleaned[key] = value

    return cleaned


def _try_resolve(
    service: str,
    key: str,
    env_var: str,
    store: Optional[CredentialStore],
) -> Optional[str]:
    """Intenta resolver un secreto desde el store."""
    if not store or not store.has(service):
        return None
    try:
        creds = store.retrieve(service)
        return creds.get(key) or creds.get("api_key")
    except Exception:
        return None
