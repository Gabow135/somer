"""Auditoría de seguridad de configuración — SOMER 2.0.

Portado de OpenClaw: audit.ts, audit-extra.sync.ts, audit-extra.async.ts,
audit-channel.ts, fix.ts.

Sistema integral de auditoría con chequeos sincronos (config, permisos,
secretos), asincronos (conectividad, salud de servicios, API keys) y
auditorías por canal. Incluye sistema de auto-fix.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform as platform_mod
import re
import stat
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional, Set, Tuple

from pydantic import BaseModel, Field

from config.schema import (
    ChannelConfig,
    GatewayConfig,
    SecurityConfig,
    SomerConfig,
)
from shared.constants import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_CREDENTIALS_DIR,
    DEFAULT_HOME,
    DEFAULT_LOGS_DIR,
    DEFAULT_MEMORY_DIR,
    DEFAULT_SESSIONS_DIR,
    GATEWAY_HOST,
    GATEWAY_PORT,
)
from shared.errors import AuditFailureError, SecurityError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tipos y modelos Pydantic
# ---------------------------------------------------------------------------

AuditSeverity = Literal["critical", "warning", "info"]


class AuditFinding(BaseModel):
    """Hallazgo individual de auditoría de seguridad."""

    check_id: str
    severity: AuditSeverity
    title: str
    detail: str
    remediation: Optional[str] = None
    auto_fixable: bool = False


class AuditSummary(BaseModel):
    """Resumen cuantitativo del reporte de auditoría."""

    critical: int = 0
    warning: int = 0
    info: int = 0


class GatewayProbeResult(BaseModel):
    """Resultado de la prueba de conectividad al gateway."""

    attempted: bool = False
    url: Optional[str] = None
    ok: bool = False
    error: Optional[str] = None
    latency_ms: Optional[float] = None


class DeepAuditResult(BaseModel):
    """Resultados de la auditoría profunda (con I/O)."""

    gateway: Optional[GatewayProbeResult] = None


class AuditReport(BaseModel):
    """Reporte completo de auditoría de seguridad."""

    timestamp: float = Field(default_factory=time.time)
    summary: AuditSummary = Field(default_factory=AuditSummary)
    findings: List[AuditFinding] = Field(default_factory=list)
    deep: Optional[DeepAuditResult] = None


class FixAction(BaseModel):
    """Acción de corrección ejecutada."""

    kind: Literal["chmod", "config", "mkdir"]
    path: str
    detail: str
    ok: bool = False
    skipped: Optional[str] = None
    error: Optional[str] = None


class FixResult(BaseModel):
    """Resultado de la corrección automática de seguridad."""

    ok: bool = True
    state_dir: str = ""
    config_path: str = ""
    config_written: bool = False
    changes: List[str] = Field(default_factory=list)
    actions: List[FixAction] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class AuditOptions(BaseModel):
    """Opciones para ejecutar la auditoría."""

    config: Optional[SomerConfig] = None
    deep: bool = False
    include_filesystem: bool = True
    include_channels: bool = True
    state_dir: Optional[str] = None
    config_path: Optional[str] = None
    deep_timeout_secs: float = 5.0

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Constantes internas
# ---------------------------------------------------------------------------

# Carpetas de sincronización cloud que representan riesgo
_SYNCED_DIR_MARKERS = ("icloud", "dropbox", "google drive", "googledrive", "onedrive")

# Patrones de modelos legacy / poco seguros
_LEGACY_MODEL_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bgpt-3\.5\b", re.IGNORECASE), "Familia GPT-3.5"),
    (re.compile(r"\bclaude-(instant|2)\b", re.IGNORECASE), "Familia Claude 2/Instant"),
    (re.compile(r"\bgpt-4-(0314|0613)\b", re.IGNORECASE), "Snapshots legacy de GPT-4"),
]

_WEAK_TIER_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bhaiku\b", re.IGNORECASE), "Tier Haiku (modelo menor)"),
]

# Patrones peligrosos en skills (reutilizados de scanner.py)
_DANGEROUS_CODE_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"rm\s+-rf", re.IGNORECASE), "Comando destructivo: rm -rf"),
    (re.compile(r"eval\s*\(", re.IGNORECASE), "Uso de eval()"),
    (re.compile(r"exec\s*\(", re.IGNORECASE), "Uso de exec()"),
    (re.compile(r"subprocess\.call", re.IGNORECASE), "subprocess.call sin shell=False"),
    (re.compile(r"os\.system\s*\(", re.IGNORECASE), "Uso de os.system()"),
    (re.compile(r"shell\s*=\s*True", re.IGNORECASE), "shell=True en subprocess"),
    (re.compile(r"__import__\s*\(", re.IGNORECASE), "__import__() dinámico"),
    (re.compile(r"ctypes\.", re.IGNORECASE), "Uso de ctypes"),
    (re.compile(r"socket\.socket\s*\(", re.IGNORECASE), "Socket raw"),
]

# Tamaño mínimo recomendado para tokens/passwords
_MIN_TOKEN_LENGTH = 24


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_by_severity(findings: List[AuditFinding]) -> AuditSummary:
    """Cuenta hallazgos por severidad."""
    critical = sum(1 for f in findings if f.severity == "critical")
    warning = sum(1 for f in findings if f.severity == "warning")
    info = sum(1 for f in findings if f.severity == "info")
    return AuditSummary(critical=critical, warning=warning, info=info)


def _is_synced_path(p: str) -> bool:
    """Detecta si una ruta parece estar en una carpeta sincronizada."""
    lower = p.lower()
    return any(marker in lower for marker in _SYNCED_DIR_MARKERS)


def _looks_like_env_ref(value: str) -> bool:
    """Detecta si un valor parece una referencia a variable de entorno."""
    v = value.strip()
    return v.startswith("${") and v.endswith("}")


def _has_non_empty_string(value: Any) -> bool:
    """Verifica si un valor es un string no vacío."""
    return isinstance(value, str) and len(value.strip()) > 0


def _check_path_permissions(
    target: Path,
) -> Optional[Dict[str, Any]]:
    """Inspecciona permisos de un path.

    Returns:
        Dict con propiedades del path, o None si no existe.
    """
    try:
        st = target.lstat()
    except OSError:
        return None

    mode = st.st_mode
    is_symlink = stat.S_ISLNK(mode)

    # Si es symlink, obtener stat del target real
    if is_symlink:
        try:
            st = target.stat()
            mode = st.st_mode
        except OSError:
            return {"ok": True, "is_symlink": True, "exists": False}

    perms = mode & 0o777
    return {
        "ok": True,
        "is_symlink": is_symlink,
        "is_dir": stat.S_ISDIR(mode),
        "is_file": stat.S_ISREG(mode),
        "mode": perms,
        "world_writable": bool(perms & stat.S_IWOTH),
        "group_writable": bool(perms & stat.S_IWGRP),
        "world_readable": bool(perms & stat.S_IROTH),
        "group_readable": bool(perms & stat.S_IRGRP),
    }


def _format_permission_detail(path: Path, perms: Dict[str, Any]) -> str:
    """Formatea detalle de permisos."""
    return f"{path} (permisos: {oct(perms['mode'])})"


def _format_permission_remediation(path: Path, target_mode: int) -> str:
    """Genera remediación para permisos."""
    return f"chmod {oct(target_mode)} {path}"


# ---------------------------------------------------------------------------
# Chequeos sincrónicos — Superficie de ataque y configuración
# ---------------------------------------------------------------------------

def _collect_attack_surface_summary(config: SomerConfig) -> List[AuditFinding]:
    """Genera un resumen de la superficie de ataque."""
    channels_enabled = sum(1 for c in config.channels.entries.values() if c.enabled)
    providers_enabled = sum(1 for p in config.providers.values() if p.enabled)

    detail = (
        f"canales habilitados: {channels_enabled}\n"
        f"providers habilitados: {providers_enabled}\n"
        f"gateway: {config.gateway.host}:{config.gateway.port}\n"
        f"memoria: {'habilitada' if config.memory.enabled else 'deshabilitada'}\n"
        f"block_dangerous_skills: {config.security.block_dangerous_skills}\n"
        f"audit_on_start: {config.security.audit_on_start}\n"
        f"modelo de confianza: asistente personal (un operador de confianza)"
    )

    return [
        AuditFinding(
            check_id="summary.attack_surface",
            severity="info",
            title="Resumen de superficie de ataque",
            detail=detail,
        )
    ]


def _collect_synced_folder_findings(
    state_dir: str,
    config_path: str,
) -> List[AuditFinding]:
    """Detecta si state/config están en carpetas sincronizadas (iCloud, Dropbox, etc.)."""
    findings: List[AuditFinding] = []
    if _is_synced_path(state_dir) or _is_synced_path(config_path):
        findings.append(
            AuditFinding(
                check_id="fs.synced_dir",
                severity="warning",
                title="Ruta de estado/config parece estar en carpeta sincronizada",
                detail=(
                    f"state_dir={state_dir}, config_path={config_path}. "
                    "Las carpetas sincronizadas (iCloud/Dropbox/OneDrive/Google Drive) "
                    "pueden filtrar tokens y transcripciones a otros dispositivos."
                ),
                remediation=(
                    "Mover el directorio de estado a un volumen local. "
                    'Ejecutar: somer config set --key state_dir --value "/ruta/local"'
                ),
                auto_fixable=False,
            )
        )
    return findings


def _collect_gateway_config_findings(config: SomerConfig) -> List[AuditFinding]:
    """Verifica la configuración de seguridad del gateway."""
    findings: List[AuditFinding] = []
    gw = config.gateway

    # Gateway expuesto sin restricciones
    if gw.host == "0.0.0.0":
        findings.append(
            AuditFinding(
                check_id="gateway.bind_all_interfaces",
                severity="critical",
                title="Gateway expuesto en todas las interfaces",
                detail=(
                    f'gateway.host="0.0.0.0" expone el gateway a toda la red. '
                    "Cualquier proceso en la red puede conectarse."
                ),
                remediation=(
                    'Cambiar gateway.host a "127.0.0.1" (loopback) a menos que '
                    "se necesite acceso remoto con autenticación adecuada."
                ),
                auto_fixable=True,
            )
        )
    elif gw.host != "127.0.0.1" and gw.host != "localhost":
        findings.append(
            AuditFinding(
                check_id="gateway.bind_non_loopback",
                severity="warning",
                title="Gateway no está en loopback",
                detail=(
                    f'gateway.host="{gw.host}" permite conexiones más allá del loopback.'
                ),
                remediation=(
                    'Considerar gateway.host="127.0.0.1" si el acceso remoto no es necesario.'
                ),
            )
        )

    # Puerto no estándar (info)
    if gw.port != 18789:
        findings.append(
            AuditFinding(
                check_id="gateway.non_default_port",
                severity="info",
                title="Gateway usa puerto no estándar",
                detail=f"gateway.port={gw.port} (estándar: 18789).",
            )
        )

    return findings


def _collect_secrets_in_config_findings(config: SomerConfig) -> List[AuditFinding]:
    """Detecta secretos embebidos como literales en la configuración."""
    findings: List[AuditFinding] = []

    for provider_id, provider in config.providers.items():
        auth = provider.auth

        # API key como literal
        if auth.api_key and not _looks_like_env_ref(auth.api_key):
            findings.append(
                AuditFinding(
                    check_id=f"config.secrets.provider_{provider_id}_api_key",
                    severity="warning",
                    title=f"API key de {provider_id} como literal en config",
                    detail=(
                        f"providers.{provider_id}.auth.api_key contiene una clave literal. "
                        "Prefiere variables de entorno o archivos de credenciales."
                    ),
                    remediation=(
                        f"Usar api_key_env con la variable de entorno apropiada "
                        f"(ej: {provider_id.upper()}_API_KEY) y eliminar api_key de la config."
                    ),
                    auto_fixable=False,
                )
            )

        # base_url apuntando a HTTP sin TLS (no localhost)
        if auth.base_url:
            url = auth.base_url.lower()
            if url.startswith("http://") and "localhost" not in url and "127.0.0.1" not in url:
                findings.append(
                    AuditFinding(
                        check_id=f"config.secrets.provider_{provider_id}_http_url",
                        severity="warning",
                        title=f"Provider {provider_id} usa HTTP sin TLS",
                        detail=(
                            f"providers.{provider_id}.auth.base_url usa HTTP plano. "
                            "Las credenciales pueden viajar sin cifrar."
                        ),
                        remediation="Usar HTTPS para providers remotos.",
                    )
                )

    return findings


def _collect_security_config_findings(config: SomerConfig) -> List[AuditFinding]:
    """Verifica la configuración de seguridad general."""
    findings: List[AuditFinding] = []
    sec = config.security

    if not sec.block_dangerous_skills:
        findings.append(
            AuditFinding(
                check_id="config.security.dangerous_skills_unblocked",
                severity="warning",
                title="Skills peligrosos no están bloqueados",
                detail=(
                    "security.block_dangerous_skills=false permite ejecutar "
                    "skills con patrones potencialmente peligrosos."
                ),
                remediation="Activar security.block_dangerous_skills=true.",
                auto_fixable=True,
            )
        )

    if not sec.audit_on_start:
        findings.append(
            AuditFinding(
                check_id="config.security.audit_disabled",
                severity="info",
                title="Auditoría al inicio desactivada",
                detail=(
                    "security.audit_on_start=false desactiva la auditoría automática "
                    "al iniciar SOMER."
                ),
                remediation="Considerar activar security.audit_on_start=true.",
            )
        )

    if sec.allowed_hosts:
        for host in sec.allowed_hosts:
            if host.strip() == "*":
                findings.append(
                    AuditFinding(
                        check_id="config.security.wildcard_allowed_host",
                        severity="critical",
                        title="Wildcard en hosts permitidos",
                        detail=(
                            'security.allowed_hosts contiene "*", lo que permite '
                            "cualquier host de origen."
                        ),
                        remediation="Reemplazar '*' con hosts específicos de confianza.",
                    )
                )
                break

    return findings


def _collect_model_hygiene_findings(config: SomerConfig) -> List[AuditFinding]:
    """Verifica que los modelos configurados no sean legacy o débiles."""
    findings: List[AuditFinding] = []
    models_to_check = [config.default_model, config.fast_model]

    # Agregar modelos de providers
    for provider in config.providers.values():
        if provider.default_model:
            models_to_check.append(provider.default_model)
        for model_cfg in provider.models:
            models_to_check.append(model_cfg.id)

    legacy_hits: List[Tuple[str, str]] = []
    weak_hits: List[Tuple[str, str]] = []

    for model_id in models_to_check:
        if not model_id:
            continue
        for pattern, label in _LEGACY_MODEL_PATTERNS:
            if pattern.search(model_id):
                legacy_hits.append((model_id, label))
                break
        for pattern, label in _WEAK_TIER_PATTERNS:
            if pattern.search(model_id):
                weak_hits.append((model_id, label))
                break

    if legacy_hits:
        lines = "\n".join(f"  - {m} ({r})" for m, r in legacy_hits[:12])
        findings.append(
            AuditFinding(
                check_id="models.legacy",
                severity="warning",
                title="Modelos legacy detectados en la configuración",
                detail=(
                    "Los modelos antiguos son menos robustos contra inyección de "
                    "prompt y uso indebido de herramientas.\n" + lines
                ),
                remediation=(
                    "Preferir modelos modernos e instruction-hardened para bots con "
                    "herramientas habilitadas."
                ),
            )
        )

    if weak_hits:
        lines = "\n".join(f"  - {m} ({r})" for m, r in weak_hits[:12])
        findings.append(
            AuditFinding(
                check_id="models.weak_tier",
                severity="warning",
                title="Modelos de tier bajo detectados",
                detail=(
                    "Los modelos menores son generalmente más susceptibles a "
                    "inyección de prompt.\n" + lines
                ),
                remediation=(
                    "Usar el modelo de mayor capacidad disponible para bots con "
                    "herramientas o entradas no confiables. Evitar tier Haiku; "
                    "preferir Claude 4.5+ y GPT-5+."
                ),
            )
        )

    return findings


def _collect_logging_findings(config: SomerConfig) -> List[AuditFinding]:
    """Verifica configuración de logging por seguridad."""
    findings: List[AuditFinding] = []

    # Verificar que el directorio de logs no sea world-readable
    logs_dir = DEFAULT_LOGS_DIR
    if logs_dir.exists():
        perms = _check_path_permissions(logs_dir)
        if perms and perms["world_readable"]:
            findings.append(
                AuditFinding(
                    check_id="logging.logs_dir_world_readable",
                    severity="warning",
                    title="Directorio de logs legible por otros",
                    detail=(
                        f"{_format_permission_detail(logs_dir, perms)}; los logs pueden "
                        "contener mensajes privados y output de herramientas."
                    ),
                    remediation=_format_permission_remediation(logs_dir, 0o700),
                    auto_fixable=True,
                )
            )

    return findings


def _collect_channel_config_findings(config: SomerConfig) -> List[AuditFinding]:
    """Verifica la configuración de canales por seguridad."""
    findings: List[AuditFinding] = []

    for channel_id, channel_cfg in config.channels.entries.items():
        if not channel_cfg.enabled:
            continue

        chan_config = channel_cfg.config

        # Verificar token/credenciales como literal en config de canal
        sensitive_keys = ["token", "bot_token", "api_key", "app_token", "secret"]
        for key in sensitive_keys:
            value = chan_config.get(key)
            if isinstance(value, str) and value.strip() and not _looks_like_env_ref(value):
                findings.append(
                    AuditFinding(
                        check_id=f"channels.{channel_id}.secrets_in_config",
                        severity="warning",
                        title=f"Secreto de canal {channel_id} en config",
                        detail=(
                            f"channels.{channel_id}.config.{key} contiene un secreto "
                            "como literal. Preferir variables de entorno."
                        ),
                        remediation=(
                            f"Usar variable de entorno (ej: "
                            f"{channel_id.upper()}_{key.upper()}) en lugar del literal."
                        ),
                    )
                )

        # Verificar grupo policy
        group_policy = chan_config.get("group_policy", "allowlist")
        if group_policy == "open":
            findings.append(
                AuditFinding(
                    check_id=f"channels.{channel_id}.group_policy_open",
                    severity="critical",
                    title=f"Canal {channel_id} tiene groupPolicy abierto",
                    detail=(
                        f'channels.{channel_id}.config.group_policy="open" permite que '
                        "cualquier grupo/sala acceda al bot."
                    ),
                    remediation=(
                        f'Cambiar channels.{channel_id}.config.group_policy a "allowlist" '
                        "y configurar los grupos permitidos explícitamente."
                    ),
                    auto_fixable=True,
                )
            )

        # Verificar DM policy
        dm_policy = chan_config.get("dm_policy", "pairing")
        if dm_policy == "open":
            findings.append(
                AuditFinding(
                    check_id=f"channels.{channel_id}.dm_policy_open",
                    severity="critical",
                    title=f"Canal {channel_id} tiene DMs abiertos",
                    detail=(
                        f'channels.{channel_id}.config.dm_policy="open" permite que '
                        "cualquier usuario envíe DMs al bot."
                    ),
                    remediation=(
                        f"Usar pairing/allowlist para channels.{channel_id}.config.dm_policy."
                    ),
                )
            )

        # Verificar wildcard en allowFrom
        allow_from = chan_config.get("allow_from", [])
        if isinstance(allow_from, list) and "*" in [str(x).strip() for x in allow_from]:
            findings.append(
                AuditFinding(
                    check_id=f"channels.{channel_id}.allow_from_wildcard",
                    severity="critical",
                    title=f"Canal {channel_id} tiene wildcard en allowFrom",
                    detail=(
                        f"channels.{channel_id}.config.allow_from contiene '*', "
                        "permitiendo acceso a cualquier usuario."
                    ),
                    remediation=(
                        "Reemplazar '*' con IDs de usuario específicos y de confianza."
                    ),
                )
            )

    return findings


def _collect_heartbeat_findings(config: SomerConfig) -> List[AuditFinding]:
    """Verifica configuración de heartbeat por seguridad."""
    findings: List[AuditFinding] = []
    hb = config.heartbeat

    if not hb.enabled:
        return findings

    # Heartbeat hacia canal sin configurar
    if hb.target != "none" and not hb.target_chat_id:
        findings.append(
            AuditFinding(
                check_id="heartbeat.target_no_chat_id",
                severity="warning",
                title="Heartbeat tiene target sin chat_id",
                detail=(
                    f"heartbeat.target={hb.target} pero target_chat_id está vacío. "
                    "Las alertas no se enviarán correctamente."
                ),
                remediation="Configurar heartbeat.target_chat_id con el ID del chat destino.",
            )
        )

    # Intervalo muy corto
    if hb.every < 60:
        findings.append(
            AuditFinding(
                check_id="heartbeat.interval_too_short",
                severity="warning",
                title="Intervalo de heartbeat muy corto",
                detail=(
                    f"heartbeat.every={hb.every}s es menor a 60s. "
                    "Esto puede generar costos excesivos de API."
                ),
                remediation="Aumentar heartbeat.every a al menos 300 (5 minutos).",
            )
        )

    return findings


def _collect_hooks_findings(config: SomerConfig) -> List[AuditFinding]:
    """Verifica configuración de hooks por seguridad."""
    findings: List[AuditFinding] = []

    if not config.hooks or not config.hooks.enabled:
        return findings

    for handler in config.hooks.internal.handlers:
        module_path = handler.module
        # Detectar rutas absolutas externas
        if module_path.startswith("/") or module_path.startswith("~"):
            findings.append(
                AuditFinding(
                    check_id=f"hooks.{handler.event}.external_path",
                    severity="info",
                    title=f"Hook {handler.event} referencia ruta externa",
                    detail=(
                        f"hooks.internal.handlers contiene handler para '{handler.event}' "
                        f"con módulo '{module_path}' que referencia "
                        "una ruta externa. Verificar que sea de confianza."
                    ),
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Chequeos del sistema de archivos (sincrónicos vía pathlib)
# ---------------------------------------------------------------------------

def _collect_filesystem_findings(
    state_dir: str,
    config_path: str,
) -> List[AuditFinding]:
    """Chequeos de permisos de archivos y directorios."""
    findings: List[AuditFinding] = []

    # --- State dir ---
    state_path = Path(state_dir)
    if state_path.exists():
        perms = _check_path_permissions(state_path)
        if perms:
            if perms.get("is_symlink"):
                findings.append(
                    AuditFinding(
                        check_id="fs.state_dir.symlink",
                        severity="warning",
                        title="Directorio de estado es un symlink",
                        detail=(
                            f"{state_dir} es un symlink; trátalo como un límite "
                            "de confianza adicional."
                        ),
                    )
                )
            if perms.get("world_writable"):
                findings.append(
                    AuditFinding(
                        check_id="fs.state_dir.perms_world_writable",
                        severity="critical",
                        title="Directorio de estado es world-writable",
                        detail=(
                            f"{_format_permission_detail(state_path, perms)}; otros "
                            "usuarios pueden escribir en tu estado de SOMER."
                        ),
                        remediation=_format_permission_remediation(state_path, 0o700),
                        auto_fixable=True,
                    )
                )
            elif perms.get("group_writable"):
                findings.append(
                    AuditFinding(
                        check_id="fs.state_dir.perms_group_writable",
                        severity="warning",
                        title="Directorio de estado es group-writable",
                        detail=(
                            f"{_format_permission_detail(state_path, perms)}; usuarios "
                            "del grupo pueden escribir en tu estado de SOMER."
                        ),
                        remediation=_format_permission_remediation(state_path, 0o700),
                        auto_fixable=True,
                    )
                )
            elif perms.get("group_readable") or perms.get("world_readable"):
                findings.append(
                    AuditFinding(
                        check_id="fs.state_dir.perms_readable",
                        severity="warning",
                        title="Directorio de estado es legible por otros",
                        detail=(
                            f"{_format_permission_detail(state_path, perms)}; "
                            "considerar restringir a 700."
                        ),
                        remediation=_format_permission_remediation(state_path, 0o700),
                        auto_fixable=True,
                    )
                )

    # --- Config file ---
    cfg_path = Path(config_path)
    if cfg_path.exists():
        perms = _check_path_permissions(cfg_path)
        if perms:
            skip_readable_warnings = perms.get("is_symlink", False)
            if perms.get("is_symlink"):
                findings.append(
                    AuditFinding(
                        check_id="fs.config.symlink",
                        severity="warning",
                        title="Archivo de configuración es un symlink",
                        detail=(
                            f"{config_path} es un symlink; asegúrate de confiar en su target."
                        ),
                    )
                )
            if perms.get("world_writable") or perms.get("group_writable"):
                findings.append(
                    AuditFinding(
                        check_id="fs.config.perms_writable",
                        severity="critical",
                        title="Archivo de configuración es escribible por otros",
                        detail=(
                            f"{_format_permission_detail(cfg_path, perms)}; otro usuario "
                            "podría cambiar las políticas del gateway/auth/herramientas."
                        ),
                        remediation=_format_permission_remediation(cfg_path, 0o600),
                        auto_fixable=True,
                    )
                )
            elif not skip_readable_warnings and perms.get("world_readable"):
                findings.append(
                    AuditFinding(
                        check_id="fs.config.perms_world_readable",
                        severity="critical",
                        title="Archivo de configuración es world-readable",
                        detail=(
                            f"{_format_permission_detail(cfg_path, perms)}; la config puede "
                            "contener tokens y configuración privada."
                        ),
                        remediation=_format_permission_remediation(cfg_path, 0o600),
                        auto_fixable=True,
                    )
                )
            elif not skip_readable_warnings and perms.get("group_readable"):
                findings.append(
                    AuditFinding(
                        check_id="fs.config.perms_group_readable",
                        severity="warning",
                        title="Archivo de configuración es group-readable",
                        detail=(
                            f"{_format_permission_detail(cfg_path, perms)}; la config puede "
                            "contener tokens y configuración privada."
                        ),
                        remediation=_format_permission_remediation(cfg_path, 0o600),
                        auto_fixable=True,
                    )
                )

    # --- Credentials directory ---
    creds_dir = DEFAULT_CREDENTIALS_DIR
    if creds_dir.exists():
        perms = _check_path_permissions(creds_dir)
        if perms:
            if perms.get("world_writable") or perms.get("group_writable"):
                findings.append(
                    AuditFinding(
                        check_id="fs.credentials_dir.perms_writable",
                        severity="critical",
                        title="Directorio de credenciales es escribible por otros",
                        detail=(
                            f"{_format_permission_detail(creds_dir, perms)}; otro usuario "
                            "podría modificar archivos de credenciales."
                        ),
                        remediation=_format_permission_remediation(creds_dir, 0o700),
                        auto_fixable=True,
                    )
                )
            elif perms.get("group_readable") or perms.get("world_readable"):
                findings.append(
                    AuditFinding(
                        check_id="fs.credentials_dir.perms_readable",
                        severity="warning",
                        title="Directorio de credenciales es legible por otros",
                        detail=(
                            f"{_format_permission_detail(creds_dir, perms)}; las credenciales "
                            "y allowlists pueden ser sensibles."
                        ),
                        remediation=_format_permission_remediation(creds_dir, 0o700),
                        auto_fixable=True,
                    )
                )

        # Verificar archivos individuales de credenciales
        try:
            for child in creds_dir.iterdir():
                if child.name.startswith(".") or not child.is_file():
                    continue
                child_perms = _check_path_permissions(child)
                if child_perms and (
                    child_perms.get("world_readable") or child_perms.get("group_readable")
                ):
                    findings.append(
                        AuditFinding(
                            check_id="fs.credentials_file.perms_readable",
                            severity="warning",
                            title=f"Archivo de credenciales legible por otros: {child.name}",
                            detail=(
                                f"{_format_permission_detail(child, child_perms)}; "
                                "los archivos de credenciales deben ser accesibles solo al dueño."
                            ),
                            remediation=_format_permission_remediation(child, 0o600),
                            auto_fixable=True,
                        )
                    )
        except OSError:
            pass

    # --- Sessions directory ---
    sessions_dir = DEFAULT_SESSIONS_DIR
    if sessions_dir.exists():
        perms = _check_path_permissions(sessions_dir)
        if perms and (perms.get("world_readable") or perms.get("group_readable")):
            findings.append(
                AuditFinding(
                    check_id="fs.sessions_dir.perms_readable",
                    severity="warning",
                    title="Directorio de sesiones legible por otros",
                    detail=(
                        f"{_format_permission_detail(sessions_dir, perms)}; las sesiones "
                        "contienen transcripciones y metadata de routing."
                    ),
                    remediation=_format_permission_remediation(sessions_dir, 0o700),
                    auto_fixable=True,
                )
            )

    # --- Memory directory ---
    memory_dir = DEFAULT_MEMORY_DIR
    if memory_dir.exists():
        perms = _check_path_permissions(memory_dir)
        if perms and (perms.get("world_readable") or perms.get("group_readable")):
            findings.append(
                AuditFinding(
                    check_id="fs.memory_dir.perms_readable",
                    severity="warning",
                    title="Directorio de memoria legible por otros",
                    detail=(
                        f"{_format_permission_detail(memory_dir, perms)}; la base de datos "
                        "de memoria contiene datos privados del usuario."
                    ),
                    remediation=_format_permission_remediation(memory_dir, 0o700),
                    auto_fixable=True,
                )
            )

    return findings


def _collect_env_var_findings() -> List[AuditFinding]:
    """Detecta variables de entorno sensibles y posibles fugas."""
    findings: List[AuditFinding] = []
    sensitive_prefixes = ("SOMER_", "ANTHROPIC_", "OPENAI_", "DEEPSEEK_", "GOOGLE_")
    sensitive_suffixes = ("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD")

    detected_vars: List[str] = []
    for var in os.environ:
        if any(var.startswith(p) for p in sensitive_prefixes):
            if any(var.endswith(s) for s in sensitive_suffixes):
                detected_vars.append(var)

    if detected_vars:
        findings.append(
            AuditFinding(
                check_id="env.sensitive_vars_detected",
                severity="info",
                title="Variables de entorno sensibles detectadas",
                detail=(
                    "Variables de entorno con secretos detectadas: "
                    + ", ".join(detected_vars[:10])
                    + (f" (+{len(detected_vars) - 10} más)" if len(detected_vars) > 10 else "")
                    + ". Esto es esperado si se usan para configuración segura."
                ),
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Chequeos asincrónicos — Conectividad y servicios
# ---------------------------------------------------------------------------

async def _probe_gateway(
    config: SomerConfig,
    timeout_secs: float = 5.0,
) -> GatewayProbeResult:
    """Intenta conectar al gateway WebSocket para verificar que funciona."""
    url = f"ws://{config.gateway.host}:{config.gateway.port}"
    result = GatewayProbeResult(attempted=True, url=url)

    try:
        import websockets
    except ImportError:
        result.error = "websockets no está instalado; no se puede probar el gateway"
        return result

    try:
        start = time.monotonic()
        async with websockets.connect(  # type: ignore[attr-defined]
            url,
            open_timeout=timeout_secs,
            close_timeout=2.0,
        ) as ws:
            latency = (time.monotonic() - start) * 1000
            result.ok = True
            result.latency_ms = round(latency, 2)
            await ws.close()
    except asyncio.TimeoutError:
        result.error = f"Timeout al conectar al gateway ({timeout_secs}s)"
    except ConnectionRefusedError:
        result.error = "Conexión rechazada — el gateway probablemente no está corriendo"
    except Exception as exc:
        result.error = f"Error al conectar: {exc}"

    return result


async def _validate_provider_api_keys(config: SomerConfig) -> List[AuditFinding]:
    """Verifica que las API keys de los providers estén configuradas y sean válidas."""
    findings: List[AuditFinding] = []

    for provider_id, provider in config.providers.items():
        if not provider.enabled:
            continue

        auth = provider.auth
        has_key = False

        # Verificar API key via env
        if auth.api_key_env:
            env_val = os.environ.get(auth.api_key_env)
            if env_val and env_val.strip():
                has_key = True
            else:
                findings.append(
                    AuditFinding(
                        check_id=f"providers.{provider_id}.api_key_env_missing",
                        severity="warning",
                        title=f"Variable de entorno de API key para {provider_id} no existe",
                        detail=(
                            f"providers.{provider_id}.auth.api_key_env='{auth.api_key_env}' "
                            "pero la variable de entorno no está definida o está vacía."
                        ),
                        remediation=(
                            f"Exportar la variable: export {auth.api_key_env}='tu-api-key'"
                        ),
                    )
                )

        # Verificar API key via file
        if auth.api_key_file:
            key_path = Path(auth.api_key_file).expanduser()
            if key_path.exists():
                has_key = True
                # Verificar permisos del archivo de key
                perms = _check_path_permissions(key_path)
                if perms and (
                    perms.get("world_readable") or perms.get("group_readable")
                ):
                    findings.append(
                        AuditFinding(
                            check_id=f"providers.{provider_id}.api_key_file_perms",
                            severity="critical",
                            title=f"Archivo de API key de {provider_id} legible por otros",
                            detail=(
                                f"{_format_permission_detail(key_path, perms)}; "
                                "la API key puede ser leída por otros usuarios."
                            ),
                            remediation=_format_permission_remediation(key_path, 0o600),
                            auto_fixable=True,
                        )
                    )
            else:
                findings.append(
                    AuditFinding(
                        check_id=f"providers.{provider_id}.api_key_file_missing",
                        severity="warning",
                        title=f"Archivo de API key de {provider_id} no existe",
                        detail=(
                            f"providers.{provider_id}.auth.api_key_file='{auth.api_key_file}' "
                            "no existe."
                        ),
                        remediation=f"Crear el archivo: echo 'tu-key' > {auth.api_key_file}",
                    )
                )

        # API key literal
        if auth.api_key and auth.api_key.strip():
            has_key = True

        if not has_key:
            findings.append(
                AuditFinding(
                    check_id=f"providers.{provider_id}.no_api_key",
                    severity="critical",
                    title=f"Provider {provider_id} habilitado sin API key",
                    detail=(
                        f"providers.{provider_id} está habilitado pero no tiene ninguna "
                        "fuente de API key configurada (api_key_env, api_key_file, api_key)."
                    ),
                    remediation=(
                        f"Configurar al menos una fuente de API key para {provider_id}, "
                        "preferiblemente via variable de entorno."
                    ),
                )
            )

    return findings


async def _collect_skill_code_safety_findings(
    config: SomerConfig,
) -> List[AuditFinding]:
    """Escanea directorios de skills en busca de patrones de código peligrosos."""
    findings: List[AuditFinding] = []

    for skills_dir_str in config.skills.dirs:
        skills_dir = Path(skills_dir_str)
        if not skills_dir.exists() or not skills_dir.is_dir():
            continue

        for skill_path in skills_dir.rglob("SKILL.md"):
            try:
                content = skill_path.read_text(encoding="utf-8")
            except OSError:
                continue

            skill_name = skill_path.parent.name
            dangerous_hits: List[str] = []

            for pattern, description in _DANGEROUS_CODE_PATTERNS:
                if pattern.search(content):
                    dangerous_hits.append(description)

            if dangerous_hits:
                severity: AuditSeverity = (
                    "critical" if len(dangerous_hits) >= 3 else "warning"
                )
                findings.append(
                    AuditFinding(
                        check_id=f"skills.code_safety.{skill_name}",
                        severity=severity,
                        title=f"Skill '{skill_name}' contiene patrones de código peligrosos",
                        detail=(
                            f"Encontrados {len(dangerous_hits)} patrón(es) peligroso(s) en "
                            f"{skill_path}:\n"
                            + "\n".join(f"  - {h}" for h in dangerous_hits)
                        ),
                        remediation=(
                            "Revisar el código fuente del skill cuidadosamente antes de usar. "
                            f"Si no es confiable, eliminar '{skill_path.parent}'."
                        ),
                    )
                )

            # Verificar symlinks que escapan del directorio de skills
            try:
                real_path = skill_path.resolve()
                skills_real = skills_dir.resolve()
                if not str(real_path).startswith(str(skills_real)):
                    findings.append(
                        AuditFinding(
                            check_id=f"skills.symlink_escape.{skill_name}",
                            severity="warning",
                            title=f"Skill '{skill_name}' symlink escapa del directorio",
                            detail=(
                                f"El skill {skill_path} resuelve a {real_path}, "
                                f"que está fuera de {skills_real}."
                            ),
                            remediation=(
                                "Mantener los skills dentro del directorio raíz de skills. "
                                "Reemplazar symlinks con archivos reales."
                            ),
                        )
                    )
            except OSError:
                pass

    return findings


async def _collect_network_exposure_findings(config: SomerConfig) -> List[AuditFinding]:
    """Evalúa la exposición de red del sistema."""
    findings: List[AuditFinding] = []
    gw = config.gateway
    is_exposed = gw.host not in ("127.0.0.1", "localhost", "::1")

    # Canales habilitados con gateway expuesto
    if is_exposed:
        open_channels = [
            cid for cid, c in config.channels.entries.items()
            if c.enabled and c.config.get("group_policy") == "open"
        ]
        if open_channels:
            findings.append(
                AuditFinding(
                    check_id="security.exposure.open_channels_exposed_gateway",
                    severity="critical",
                    title="Canales abiertos con gateway expuesto",
                    detail=(
                        f"Gateway expuesto en {gw.host}:{gw.port} con canales "
                        f"de grupo abierto: {', '.join(open_channels)}. "
                        "Una inyección de prompt en esos grupos puede escalar "
                        "a acciones de alto impacto."
                    ),
                    remediation=(
                        'Cambiar group_policy a "allowlist" para canales expuestos '
                        "y mantener el gateway en loopback."
                    ),
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Auditoría específica de canales
# ---------------------------------------------------------------------------

async def _collect_channel_security_findings(
    config: SomerConfig,
) -> List[AuditFinding]:
    """Auditoría de seguridad específica por canal."""
    findings: List[AuditFinding] = []

    for channel_id, channel_cfg in config.channels.entries.items():
        if not channel_cfg.enabled:
            continue

        chan_config = channel_cfg.config

        # --- Telegram-specific ---
        if channel_id == "telegram":
            # Verificar que allowFrom tenga IDs numéricos
            allow_from = chan_config.get("allow_from", [])
            if isinstance(allow_from, list):
                non_numeric = [
                    str(e) for e in allow_from
                    if str(e).strip() and str(e).strip() != "*"
                    and not str(e).strip().lstrip("-").isdigit()
                ]
                if non_numeric:
                    findings.append(
                        AuditFinding(
                            check_id="channels.telegram.allow_from.non_numeric",
                            severity="warning",
                            title="Telegram allowFrom contiene entradas no numéricas",
                            detail=(
                                "La autorización de sender en Telegram requiere IDs numéricos. "
                                f"Entradas no numéricas encontradas: {', '.join(non_numeric[:5])}"
                                + (f" (+{len(non_numeric) - 5} más)" if len(non_numeric) > 5 else "")
                            ),
                            remediation=(
                                "Reemplazar @username con IDs numéricos de Telegram."
                            ),
                        )
                    )

            # Verificar grupo allowFrom wildcard
            group_allow_from = chan_config.get("group_allow_from", [])
            if isinstance(group_allow_from, list):
                if any(str(v).strip() == "*" for v in group_allow_from):
                    findings.append(
                        AuditFinding(
                            check_id="channels.telegram.group_allow_from.wildcard",
                            severity="critical",
                            title="Telegram group allowFrom contiene wildcard",
                            detail=(
                                'Telegram group_allow_from contiene "*", lo que permite '
                                "que cualquier miembro del grupo ejecute comandos."
                            ),
                            remediation=(
                                "Eliminar '*' de group_allow_from y usar IDs numéricos "
                                "de Telegram explícitos."
                            ),
                        )
                    )

        # --- Discord-specific ---
        elif channel_id == "discord":
            # Verificar name-based allow entries (mutable identity)
            allow_from = chan_config.get("allow_from", [])
            if isinstance(allow_from, list):
                name_based = [
                    str(e) for e in allow_from
                    if isinstance(e, str) and e.strip()
                    and not e.strip().startswith("<@")
                    and not e.strip().startswith("user:")
                    and not e.strip().lstrip("-").isdigit()
                    and e.strip() != "*"
                ]
                if name_based:
                    findings.append(
                        AuditFinding(
                            check_id="channels.discord.allow_from.name_based",
                            severity="warning",
                            title="Discord allowFrom contiene entradas basadas en nombre",
                            detail=(
                                "Las entradas basadas en nombre/tag de Discord usan "
                                "slugs normalizados y pueden colisionar entre usuarios. "
                                f"Encontradas: {', '.join(name_based[:5])}"
                                + (f" (+{len(name_based) - 5} más)" if len(name_based) > 5 else "")
                            ),
                            remediation=(
                                "Preferir IDs estables de Discord (ej: <@id> o user:<id>) "
                                "en channels.discord.allow_from."
                            ),
                        )
                    )

        # --- Slack-specific ---
        elif channel_id == "slack":
            # Verificar slash commands sin access groups
            commands_cfg = chan_config.get("commands", {})
            if isinstance(commands_cfg, dict):
                native_enabled = commands_cfg.get("native", False)
                use_access_groups = commands_cfg.get("use_access_groups", True)
                if native_enabled and not use_access_groups:
                    findings.append(
                        AuditFinding(
                            check_id="channels.slack.commands.no_access_groups",
                            severity="critical",
                            title="Slash commands de Slack sin access groups",
                            detail=(
                                "Slash commands de Slack habilitados con "
                                "use_access_groups=false; esto permite ejecución "
                                "no restringida de comandos /..."
                            ),
                            remediation=(
                                "Activar commands.use_access_groups=true (recomendado)."
                            ),
                        )
                    )

    return findings


# ---------------------------------------------------------------------------
# Sistema de auto-fix
# ---------------------------------------------------------------------------

def _safe_chmod(target: Path, mode: int, require: str = "any") -> FixAction:
    """Aplica chmod de forma segura."""
    action = FixAction(
        kind="chmod",
        path=str(target),
        detail=f"chmod {oct(mode)} {target}",
    )

    try:
        st = target.lstat()

        # No modificar symlinks
        if stat.S_ISLNK(st.st_mode):
            action.skipped = "symlink"
            return action

        if require == "dir" and not stat.S_ISDIR(st.st_mode):
            action.skipped = "no es directorio"
            return action
        if require == "file" and not stat.S_ISREG(st.st_mode):
            action.skipped = "no es archivo"
            return action

        current = st.st_mode & 0o777
        if current == mode:
            action.skipped = "ya tiene los permisos correctos"
            return action

        target.chmod(mode)
        action.ok = True

    except FileNotFoundError:
        action.skipped = "no existe"
    except OSError as exc:
        action.error = str(exc)

    return action


async def fix_security_issues(
    config: Optional[SomerConfig] = None,
    state_dir: Optional[str] = None,
    config_path: Optional[str] = None,
) -> FixResult:
    """Aplica correcciones automáticas de seguridad.

    Corrige permisos de archivos/directorios y configuración insegura.

    Args:
        config: Configuración actual (si None, usa defaults).
        state_dir: Directorio de estado (si None, usa DEFAULT_HOME).
        config_path: Ruta de config (si None, usa DEFAULT_CONFIG_PATH).

    Returns:
        FixResult con detalle de acciones ejecutadas.
    """
    sd = state_dir or str(DEFAULT_HOME)
    cp = config_path or str(DEFAULT_CONFIG_PATH)
    result = FixResult(state_dir=sd, config_path=cp)

    # --- Fix permisos del filesystem ---

    # State dir -> 700
    sd_path = Path(sd)
    if sd_path.exists():
        result.actions.append(_safe_chmod(sd_path, 0o700, require="dir"))

    # Config file -> 600
    cp_path = Path(cp)
    if cp_path.exists():
        result.actions.append(_safe_chmod(cp_path, 0o600, require="file"))

    # Credentials dir -> 700 y archivos -> 600
    creds_dir = DEFAULT_CREDENTIALS_DIR
    if creds_dir.exists():
        result.actions.append(_safe_chmod(creds_dir, 0o700, require="dir"))
        try:
            for child in creds_dir.iterdir():
                if child.is_file() and not child.name.startswith("."):
                    result.actions.append(_safe_chmod(child, 0o600, require="file"))
        except OSError as exc:
            result.errors.append(f"Error listando credenciales: {exc}")

    # Sessions dir -> 700
    sessions_dir = DEFAULT_SESSIONS_DIR
    if sessions_dir.exists():
        result.actions.append(_safe_chmod(sessions_dir, 0o700, require="dir"))
        # Archivos de sesión -> 600
        try:
            for child in sessions_dir.iterdir():
                if child.is_file() and child.suffix in (".jsonl", ".json"):
                    result.actions.append(_safe_chmod(child, 0o600, require="file"))
        except OSError as exc:
            result.errors.append(f"Error listando sesiones: {exc}")

    # Memory dir -> 700
    memory_dir = DEFAULT_MEMORY_DIR
    if memory_dir.exists():
        result.actions.append(_safe_chmod(memory_dir, 0o700, require="dir"))

    # Logs dir -> 700
    logs_dir = DEFAULT_LOGS_DIR
    if logs_dir.exists():
        result.actions.append(_safe_chmod(logs_dir, 0o700, require="dir"))

    # --- Fix configuración ---
    if config:
        changes: List[str] = []

        # Fix gateway expuesto
        if config.gateway.host == "0.0.0.0":
            config.gateway.host = "127.0.0.1"
            changes.append('gateway.host="0.0.0.0" -> "127.0.0.1"')

        # Fix dangerous skills unblocked
        if not config.security.block_dangerous_skills:
            config.security.block_dangerous_skills = True
            changes.append("security.block_dangerous_skills=false -> true")

        # Fix group policies open -> allowlist
        for channel_id, channel_cfg in config.channels.entries.items():
            if not channel_cfg.enabled:
                continue
            gp = channel_cfg.config.get("group_policy")
            if gp == "open":
                channel_cfg.config["group_policy"] = "allowlist"
                changes.append(
                    f'channels.{channel_id}.config.group_policy="open" -> "allowlist"'
                )

        # Fix wildcard in allowed_hosts
        if config.security.allowed_hosts:
            original = list(config.security.allowed_hosts)
            filtered = [h for h in original if h.strip() != "*"]
            if len(filtered) != len(original):
                config.security.allowed_hosts = filtered
                changes.append("security.allowed_hosts: eliminado wildcard '*'")

        if changes:
            result.changes = changes
            # Nota: la escritura real de la config la maneja el caller
            # Aquí solo registramos los cambios aplicados al objeto
            result.config_written = True

    # Calcular resultado global
    result.ok = len(result.errors) == 0
    return result


# ---------------------------------------------------------------------------
# Función principal de auditoría
# ---------------------------------------------------------------------------

async def run_security_audit(opts: Optional[AuditOptions] = None) -> AuditReport:
    """Ejecuta una auditoría completa de seguridad.

    Combina chequeos sincrónicos (config, permisos, secretos) con
    chequeos asincrónicos (conectividad, API keys, code safety) y
    auditorías específicas por canal.

    Args:
        opts: Opciones de auditoría. Si None, usa configuración por defecto.

    Returns:
        AuditReport con todos los hallazgos.
    """
    if opts is None:
        opts = AuditOptions()

    config = opts.config or SomerConfig()
    state_dir = opts.state_dir or str(DEFAULT_HOME)
    config_path = opts.config_path or str(DEFAULT_CONFIG_PATH)
    deep = opts.deep
    include_fs = opts.include_filesystem
    include_channels = opts.include_channels

    findings: List[AuditFinding] = []

    # ── Chequeos sincrónicos de configuración ──────────────────
    findings.extend(_collect_attack_surface_summary(config))
    findings.extend(_collect_synced_folder_findings(state_dir, config_path))
    findings.extend(_collect_gateway_config_findings(config))
    findings.extend(_collect_secrets_in_config_findings(config))
    findings.extend(_collect_security_config_findings(config))
    findings.extend(_collect_model_hygiene_findings(config))
    findings.extend(_collect_logging_findings(config))
    findings.extend(_collect_channel_config_findings(config))
    findings.extend(_collect_heartbeat_findings(config))
    findings.extend(_collect_hooks_findings(config))
    findings.extend(_collect_env_var_findings())

    # ── Chequeos de filesystem ─────────────────────────────────
    if include_fs:
        findings.extend(
            _collect_filesystem_findings(state_dir, config_path)
        )

    # ── Chequeos asincrónicos ──────────────────────────────────
    # Validar API keys de providers
    findings.extend(await _validate_provider_api_keys(config))

    # Escanear code safety de skills
    findings.extend(await _collect_skill_code_safety_findings(config))

    # Evaluar exposición de red
    findings.extend(await _collect_network_exposure_findings(config))

    # ── Auditoría de canales ───────────────────────────────────
    if include_channels:
        findings.extend(await _collect_channel_security_findings(config))

    # ── Deep audit (gateway probe) ─────────────────────────────
    deep_result: Optional[DeepAuditResult] = None
    if deep:
        gateway_probe = await _probe_gateway(
            config, timeout_secs=opts.deep_timeout_secs
        )
        deep_result = DeepAuditResult(gateway=gateway_probe)

        if gateway_probe.attempted and not gateway_probe.ok:
            findings.append(
                AuditFinding(
                    check_id="gateway.probe_failed",
                    severity="warning",
                    title="Probe del gateway falló (deep)",
                    detail=gateway_probe.error or "gateway inaccesible",
                    remediation=(
                        'Ejecutar "somer doctor check" para depurar conectividad, '
                        'luego re-ejecutar "somer doctor audit --deep".'
                    ),
                )
            )

    # ── Deduplicar y construir reporte ─────────────────────────
    findings = _dedupe_findings(findings)
    summary = _count_by_severity(findings)

    return AuditReport(
        timestamp=time.time(),
        summary=summary,
        findings=findings,
        deep=deep_result,
    )


def _dedupe_findings(findings: List[AuditFinding]) -> List[AuditFinding]:
    """Elimina hallazgos duplicados basándose en check_id + detail."""
    seen: Set[str] = set()
    result: List[AuditFinding] = []
    for f in findings:
        key = f"{f.check_id}|{f.severity}|{f.detail}"
        if key in seen:
            continue
        seen.add(key)
        result.append(f)
    return result


# ---------------------------------------------------------------------------
# Funciones de conveniencia
# ---------------------------------------------------------------------------

def audit_config(config: SomerConfig) -> AuditReport:
    """Auditoría síncrona rápida de configuración (sin deep ni I/O de red).

    Wrapper síncrono para uso simple desde CLI y pruebas.
    Ejecuta el loop de asyncio internamente.

    Args:
        config: Configuración a auditar.

    Returns:
        AuditReport con hallazgos.
    """
    opts = AuditOptions(config=config, deep=False, include_filesystem=True)
    return asyncio.get_event_loop().run_until_complete(run_security_audit(opts))


async def audit_config_async(
    config: SomerConfig,
    deep: bool = False,
) -> AuditReport:
    """Auditoría asíncrona completa.

    Args:
        config: Configuración a auditar.
        deep: Si True, incluye probe del gateway y otros chequeos I/O.

    Returns:
        AuditReport con hallazgos.
    """
    return await run_security_audit(
        AuditOptions(config=config, deep=deep)
    )


def audit_credentials_dir(path: Path) -> List[AuditFinding]:
    """Audita permisos del directorio de credenciales.

    Args:
        path: Ruta al directorio de credenciales.

    Returns:
        Lista de hallazgos de seguridad.
    """
    findings: List[AuditFinding] = []

    if not path.exists():
        findings.append(
            AuditFinding(
                check_id="credentials.dir_missing",
                severity="info",
                title="Directorio de credenciales no existe",
                detail=f"{path} no existe. Se creará cuando sea necesario.",
            )
        )
        return findings

    perms = _check_path_permissions(path)
    if perms and (perms.get("world_writable") or perms.get("group_writable")):
        findings.append(
            AuditFinding(
                check_id="credentials.dir_writable",
                severity="critical",
                title="Directorio de credenciales escribible por otros",
                detail=f"{_format_permission_detail(path, perms)}",
                remediation=_format_permission_remediation(path, 0o700),
                auto_fixable=True,
            )
        )

    try:
        for f in path.iterdir():
            if f.name.startswith(".") or not f.is_file():
                continue
            f_perms = _check_path_permissions(f)
            if f_perms:
                mode = f_perms["mode"]
                if mode & 0o077:  # Cualquier permiso para group/other
                    findings.append(
                        AuditFinding(
                            check_id=f"credentials.file_perms.{f.name}",
                            severity="warning",
                            title=f"Archivo de credenciales con permisos abiertos: {f.name}",
                            detail=(
                                f"{_format_permission_detail(f, f_perms)}; "
                                "debería ser accesible solo al dueño."
                            ),
                            remediation=_format_permission_remediation(f, 0o600),
                            auto_fixable=True,
                        )
                    )
    except OSError:
        pass

    return findings


# ---------------------------------------------------------------------------
# Utilidades de formateo para CLI
# ---------------------------------------------------------------------------

_SEVERITY_ICONS = {
    "critical": "[CRIT]",
    "warning": "[WARN]",
    "info": "[INFO]",
}

_SEVERITY_COLORS = {
    "critical": "red",
    "warning": "yellow",
    "info": "blue",
}


def format_finding_for_cli(finding: AuditFinding) -> str:
    """Formatea un hallazgo para output en CLI."""
    icon = _SEVERITY_ICONS.get(finding.severity, "[????]")
    lines = [f"{icon} {finding.title}"]
    lines.append(f"       {finding.detail}")
    if finding.remediation:
        lines.append(f"       Remediación: {finding.remediation}")
    if finding.auto_fixable:
        lines.append("       (auto-fixable con --fix)")
    return "\n".join(lines)


def format_report_for_cli(report: AuditReport) -> str:
    """Formatea un reporte completo para output en CLI."""
    lines: List[str] = []
    lines.append("=" * 60)
    lines.append("  SOMER 2.0 — Auditoría de seguridad")
    lines.append("=" * 60)
    lines.append("")

    s = report.summary
    lines.append(
        f"  Resumen: {s.critical} críticos, {s.warning} advertencias, {s.info} informativos"
    )
    lines.append("")

    if report.deep and report.deep.gateway:
        gw = report.deep.gateway
        status = "OK" if gw.ok else f"FALLO ({gw.error})"
        latency = f" ({gw.latency_ms}ms)" if gw.latency_ms else ""
        lines.append(f"  Gateway probe: {status}{latency}")
        lines.append("")

    # Agrupar por severidad
    for severity in ("critical", "warning", "info"):
        group = [f for f in report.findings if f.severity == severity]
        if not group:
            continue
        label = {"critical": "CRÍTICOS", "warning": "ADVERTENCIAS", "info": "INFORMATIVOS"}
        lines.append(f"── {label[severity]} ({len(group)}) ──")
        lines.append("")
        for finding in group:
            lines.append(format_finding_for_cli(finding))
            lines.append("")

    lines.append("=" * 60)
    if s.critical > 0:
        lines.append(
            f"  {s.critical} hallazgo(s) crítico(s). "
            "Ejecutar 'somer doctor audit --fix' para correcciones automáticas."
        )
    elif s.warning > 0:
        lines.append(
            f"  {s.warning} advertencia(s). Revisar las remediaciones sugeridas."
        )
    else:
        lines.append("  Sin hallazgos de seguridad significativos.")

    return "\n".join(lines)
