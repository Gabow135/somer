"""Excepciones personalizadas de SOMER 2.0."""


class SomerError(Exception):
    """Base para todas las excepciones de SOMER."""


# ── Configuración ────────────────────────────────────────────
class ConfigError(SomerError):
    """Error en la configuración."""


class ConfigNotFoundError(ConfigError):
    """Archivo de configuración no encontrado."""


class ConfigValidationError(ConfigError):
    """Configuración no pasa validación."""


# ── Secrets ──────────────────────────────────────────────────
class SecretError(SomerError):
    """Error en el sistema de secretos."""


class SecretNotFoundError(SecretError):
    """Secreto no encontrado."""


class SecretDecryptionError(SecretError):
    """Error al descifrar un secreto."""


class SecretRefResolutionError(SecretError):
    """No se pudo resolver un SecretRef."""


class SecretProviderResolutionError(SecretError):
    """Error al resolver secretos desde un provider específico.

    Portado de OpenClaw: resolve.ts SecretProviderResolutionError.
    """

    def __init__(
        self,
        message: str,
        source: str = "",
        provider: str = "",
    ):
        super().__init__(message)
        self.source = source
        self.provider = provider


class SecretValidationError(SecretError):
    """Error en la validación de un secreto."""


class SecretRotationError(SecretError):
    """Error al rotar una credencial."""


# ── Gateway ──────────────────────────────────────────────────
class GatewayError(SomerError):
    """Error del gateway."""


class GatewayConnectionError(GatewayError):
    """No se pudo conectar al gateway."""


class GatewayMethodNotFoundError(GatewayError):
    """Método RPC no encontrado."""


# ── Providers ────────────────────────────────────────────────
class ProviderError(SomerError):
    """Error de provider LLM."""


class ProviderAuthError(ProviderError):
    """Error de autenticación con provider."""


class ProviderRateLimitError(ProviderError):
    """Rate limit del provider."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: float = 0):
        super().__init__(message)
        self.retry_after = retry_after


class ProviderBillingError(ProviderError):
    """Error de billing/cuota del provider."""


class ProviderModelNotFoundError(ProviderError):
    """Modelo no encontrado en el provider."""


# ── Agentes ──────────────────────────────────────────────────
class AgentError(SomerError):
    """Error en la ejecución de un agente."""


class AgentTimeoutError(AgentError):
    """Timeout en la ejecución de un agente."""


class ContextWindowExceededError(AgentError):
    """Se excedió el límite de contexto."""


# ── Routing ─────────────────────────────────────────────────
class RoutingError(SomerError):
    """Error en el sistema de routing."""


class RouteNotFoundError(RoutingError):
    """Ruta no encontrada para la combinación dada."""


class BindingNotFoundError(RoutingError):
    """Binding no encontrado."""


class InvalidRouteKeyError(RoutingError):
    """Clave de ruta inválida o mal formada."""


# ── Canales ──────────────────────────────────────────────────
class ChannelError(SomerError):
    """Error en un canal de comunicación."""


class ChannelSetupError(ChannelError):
    """Error al configurar un canal."""


class ChannelSendError(ChannelError):
    """Error al enviar un mensaje por canal."""


# ── Sesiones ─────────────────────────────────────────────────
class SessionError(SomerError):
    """Error en el sistema de sesiones."""


class SessionNotFoundError(SessionError):
    """Sesión no encontrada."""


class SessionExpiredError(SessionError):
    """Sesión expirada."""


class SessionSendDeniedError(SessionError):
    """Envío denegado por política de sesión."""


class SessionKeyParseError(SessionError):
    """No se pudo parsear la session key."""


# ── Memory ───────────────────────────────────────────────────
class MemoryError_(SomerError):
    """Error en el sistema de memoria."""


class EmbeddingError(MemoryError_):
    """Error al generar embeddings."""


class MemoryNotFoundError(MemoryError_):
    """Entrada de memoria no encontrada."""


class MemoryCompactionError(MemoryError_):
    """Error durante compactación de memoria."""


class MemorySyncError(MemoryError_):
    """Error durante sincronización de memoria."""


class MemoryExportError(MemoryError_):
    """Error al exportar/importar memoria."""


class MemoryBatchError(MemoryError_):
    """Error en operación batch de memoria."""


# ── Skills ───────────────────────────────────────────────────
class SkillError(SomerError):
    """Error en el sistema de skills."""


class SkillNotFoundError(SkillError):
    """Skill no encontrado."""


class SkillValidationError(SkillError):
    """Skill no pasa validación."""


class SkillExecutionError(SkillError):
    """Error al ejecutar un skill."""


# ── Hooks ───────────────────────────────────────────────────
class HookError(SomerError):
    """Error en el sistema de hooks."""


class HookExecutionError(HookError):
    """Error al ejecutar un hook."""


class HookValidationError(HookError):
    """Hook no pasa validación."""


class HookInstallError(HookError):
    """Error al instalar un hook."""


class HookNotFoundError(HookError):
    """Hook no encontrado."""


# ── Security ─────────────────────────────────────────────────
class SecurityError(SomerError):
    """Error de seguridad."""


class AuditFailureError(SecurityError):
    """Fallo en auditoría de seguridad."""


# ── Cron ───────────────────────────────────────────────────
class CronError(SomerError):
    """Error en el sistema cron."""


class CronJobNotFoundError(CronError):
    """Job cron no encontrado."""


class CronExpressionError(CronError):
    """Expresión cron inválida."""


class CronJobTimeoutError(CronError):
    """Timeout en la ejecución de un job cron."""


class CronConcurrencyError(CronError):
    """Se excedió el límite de concurrencia de jobs cron."""


class CronRetryExhaustedError(CronError):
    """Se agotaron los reintentos de un job cron."""


# ── Ciberseguridad ─────────────────────────────────────────
class CybersecurityError(SomerError):
    """Error en el módulo de ciberseguridad."""


class ScanError(CybersecurityError):
    """Error durante un escaneo de seguridad."""


class ScanTimeoutError(CybersecurityError):
    """Timeout durante un escaneo de seguridad."""


# ── Reportes ─────────────────────────────────────────────
class ReportError(SomerError):
    """Error en el sistema de reportes."""


class ReportGenerationError(ReportError):
    """Error al generar un reporte."""


class ReportDeliveryError(ReportError):
    """Error al entregar un reporte."""


class ExploitError(CybersecurityError):
    """Error en la ejecución de un exploit PoC."""
