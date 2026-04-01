"""Tools de auto-mejora para el ToolRegistry del agente.

Registra herramientas que el agente puede invocar para:
- Escanear skills y aprender patrones
- Detectar y guardar credenciales
- Aplicar parches a archivos
- Validar cambios
- Reiniciar el servicio
- Consultar estado e historial
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict

from agents.tools.registry import ToolDefinition, ToolRegistry, ToolSection

logger = logging.getLogger(__name__)

_MAX_OUTPUT = 6000


def _truncate(text: str) -> str:
    if len(text) > _MAX_OUTPUT:
        return text[:_MAX_OUTPUT] + "\n...(truncado)"
    return text


# ── Handlers ──────────────────────────────────────────────


async def _scan_skills_handler(args: Dict[str, Any]) -> str:
    """Escanea skills y aprende patrones de credenciales."""
    from self_improve.engine import SelfImproveEngine

    engine = SelfImproveEngine()
    result = engine.learn_from_skills()

    return json.dumps({
        "status": "ok",
        "new_patterns": result["new_patterns"],
        "total_patterns": result["total_patterns"],
        "skills_scanned": result["skills_scanned"],
        "message": (
            f"Escaneados {result['skills_scanned']} skills. "
            f"{result['new_patterns']} patrones nuevos aprendidos. "
            f"Total: {result['total_patterns']} patrones."
        ),
    }, ensure_ascii=False)


async def _detect_credentials_handler(args: Dict[str, Any]) -> str:
    """Detecta credenciales en texto y opcionalmente las guarda."""
    from secrets.detector import CredentialDetector

    text = args.get("text", "")
    auto_save = args.get("auto_save", False)

    if not text:
        return json.dumps({"status": "error", "message": "text es requerido"})

    detector = CredentialDetector()
    report = detector.scan(text)

    result: Dict[str, Any] = {
        "status": "ok",
        "total_detected": report.total,
        "credentials": [],
    }

    for cred in report.credentials:
        result["credentials"].append({
            "env_var": cred.env_var,
            "service": cred.service,
            "masked_value": cred.masked_value,
            "kind": cred.kind,
            "confidence": cred.confidence,
            "source": cred.source,
            "already_set": cred.already_set,
        })

    if auto_save and report.new_credentials:
        saved = detector.save_detected(report)
        result["saved"] = [{"env_var": k, "masked": v} for k, v in saved]
        result["saved_count"] = len(saved)

    return json.dumps(result, ensure_ascii=False)


async def _patch_file_handler(args: Dict[str, Any]) -> str:
    """Aplica un parche a un archivo del proyecto."""
    from self_improve.engine import SelfImproveEngine

    relative_path = args.get("file_path", "")
    old_content = args.get("old_content", "")
    new_content = args.get("new_content", "")
    dry_run = args.get("dry_run", True)

    if not relative_path or not old_content or not new_content:
        return json.dumps({
            "status": "error",
            "message": "file_path, old_content y new_content son requeridos",
        })

    engine = SelfImproveEngine()
    result = engine.patch_file(
        relative_path, old_content, new_content, dry_run=dry_run,
    )

    return json.dumps({
        "status": "ok" if result.success else "error",
        "file_path": result.file_path,
        "success": result.success,
        "backup_path": result.backup_path,
        "error": result.error,
        "lines_changed": result.lines_changed,
        "dry_run": dry_run,
    }, ensure_ascii=False)


async def _revert_patch_handler(args: Dict[str, Any]) -> str:
    """Revierte un parche restaurando el backup."""
    from self_improve.engine import SelfImproveEngine

    relative_path = args.get("file_path", "")
    if not relative_path:
        return json.dumps({"status": "error", "message": "file_path requerido"})

    engine = SelfImproveEngine()
    success = engine.revert_patch(relative_path)

    return json.dumps({
        "status": "ok" if success else "error",
        "message": "Parche revertido" if success else "No se pudo revertir",
    })


async def _validate_change_handler(args: Dict[str, Any]) -> str:
    """Valida un archivo Python y opcionalmente corre tests."""
    from self_improve.engine import SelfImproveEngine

    engine = SelfImproveEngine()
    source = args.get("source", "")
    run_tests = args.get("run_tests", False)
    test_path = args.get("test_path", "tests/unit/")

    results: Dict[str, Any] = {"status": "ok"}

    if source:
        validation = engine.validate_python(source)
        results["syntax_valid"] = validation.valid
        results["syntax_errors"] = validation.errors

    if run_tests:
        passed, output = engine.run_tests(test_path)
        results["tests_passed"] = passed
        results["test_output"] = _truncate(output)

    return json.dumps(results, ensure_ascii=False)


async def _restart_service_handler(args: Dict[str, Any]) -> str:
    """Solicita reinicio del servicio SOMER."""
    from self_improve.engine import SelfImproveEngine

    reason = args.get("reason", "Auto-mejora aplicada")
    force = args.get("force", False)

    engine = SelfImproveEngine()

    if force:
        engine.force_restart()
        return json.dumps({"status": "restarting", "method": "force"})

    success = engine.request_restart(reason)
    return json.dumps({
        "status": "ok" if success else "error",
        "method": "sentinel",
        "message": "Restart solicitado via sentinel" if success else "Error solicitando restart",
    })


async def _self_improve_status_handler(args: Dict[str, Any]) -> str:
    """Retorna estado del motor de auto-mejora e historial."""
    from self_improve.engine import SelfImproveEngine

    engine = SelfImproveEngine()
    status = engine.get_status()
    history = engine.get_improvement_history(limit=args.get("limit", 10))

    return json.dumps({
        "status": status,
        "recent_improvements": history,
    }, ensure_ascii=False, indent=2)


async def _check_skill_deps_handler(args: Dict[str, Any]) -> str:
    """Verifica dependencias de un skill (env vars faltantes)."""
    from secrets.detector import CredentialDetector

    required_env = args.get("required_env", [])
    if not required_env:
        return json.dumps({"status": "error", "message": "required_env es requerido"})

    detector = CredentialDetector()
    missing = detector.check_skill_requirements(required_env)

    return json.dumps({
        "status": "ok",
        "missing": missing,
        "all_configured": len(missing) == 0,
    })


# ── Registro ──────────────────────────────────────────────


def register_self_improve_tools(registry: ToolRegistry) -> None:
    """Registra todas las tools de auto-mejora en el registry."""

    registry.register(ToolDefinition(
        id="scan_skills",
        name="scan_skills",
        description=(
            "Escanea todos los SKILL.md del proyecto y aprende patrones "
            "de credenciales nuevos. Los patrones se persisten en "
            "~/.somer/learned_patterns.json para uso automático futuro."
        ),
        parameters={
            "type": "object",
            "properties": {},
        },
        handler=_scan_skills_handler,
        section=ToolSection.RUNTIME,
        timeout_secs=30.0,
    ))

    registry.register(ToolDefinition(
        id="detect_credentials",
        name="detect_credentials",
        description=(
            "Detecta API keys, tokens y secretos en un texto. "
            "Puede guardarlos automáticamente en ~/.somer/.env si se indica."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Texto donde buscar credenciales",
                },
                "auto_save": {
                    "type": "boolean",
                    "description": "Guardar automáticamente las credenciales nuevas (default: false)",
                },
            },
            "required": ["text"],
        },
        handler=_detect_credentials_handler,
        section=ToolSection.SECURITY,
        timeout_secs=10.0,
    ))

    registry.register(ToolDefinition(
        id="patch_file",
        name="patch_file",
        description=(
            "Aplica un parche (find & replace) a un archivo del proyecto SOMER. "
            "Crea backup automático. Valida sintaxis Python antes de aplicar. "
            "Usar dry_run=true para previsualizar sin cambios."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path relativo desde la raíz del proyecto",
                },
                "old_content": {
                    "type": "string",
                    "description": "Texto exacto a reemplazar",
                },
                "new_content": {
                    "type": "string",
                    "description": "Texto de reemplazo",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Solo validar sin aplicar (default: true)",
                },
            },
            "required": ["file_path", "old_content", "new_content"],
        },
        handler=_patch_file_handler,
        section=ToolSection.FS,
        timeout_secs=15.0,
        requires_approval=True,
        dangerous=True,
    ))

    registry.register(ToolDefinition(
        id="revert_patch",
        name="revert_patch",
        description=(
            "Revierte un parche aplicado previamente restaurando el backup .bak."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path relativo del archivo parcheado",
                },
            },
            "required": ["file_path"],
        },
        handler=_revert_patch_handler,
        section=ToolSection.FS,
        timeout_secs=10.0,
    ))

    registry.register(ToolDefinition(
        id="validate_change",
        name="validate_change",
        description=(
            "Valida código Python (syntax check) y opcionalmente corre tests."
        ),
        parameters={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Código Python a validar",
                },
                "run_tests": {
                    "type": "boolean",
                    "description": "Ejecutar tests unitarios (default: false)",
                },
                "test_path": {
                    "type": "string",
                    "description": "Path relativo de tests (default: tests/unit/)",
                },
            },
        },
        handler=_validate_change_handler,
        section=ToolSection.RUNTIME,
        timeout_secs=130.0,
    ))

    registry.register(ToolDefinition(
        id="restart_service",
        name="restart_service",
        description=(
            "Solicita reinicio del servicio SOMER para aplicar cambios. "
            "Usa el RestartSentinel por defecto (graceful). "
            "Con force=true hace hard restart via os.execv."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Razón del reinicio",
                },
                "force": {
                    "type": "boolean",
                    "description": "Hard restart via os.execv (default: false)",
                },
            },
        },
        handler=_restart_service_handler,
        section=ToolSection.RUNTIME,
        timeout_secs=10.0,
        requires_approval=True,
        dangerous=True,
    ))

    registry.register(ToolDefinition(
        id="self_improve_status",
        name="self_improve_status",
        description=(
            "Muestra el estado del motor de auto-mejora: patrones aprendidos, "
            "historial de mejoras, restart pendiente, paths del proyecto."
        ),
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Máximo de registros de historial (default: 10)",
                },
            },
        },
        handler=_self_improve_status_handler,
        section=ToolSection.MONITORING,
        timeout_secs=10.0,
    ))

    registry.register(ToolDefinition(
        id="check_skill_deps",
        name="check_skill_deps",
        description=(
            "Verifica qué variables de entorno faltan para un skill. "
            "Retorna las que no están configuradas."
        ),
        parameters={
            "type": "object",
            "properties": {
                "required_env": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de variables de entorno requeridas",
                },
            },
            "required": ["required_env"],
        },
        handler=_check_skill_deps_handler,
        section=ToolSection.RUNTIME,
        timeout_secs=5.0,
    ))

    logger.debug("Self-improve tools registradas: 8 herramientas")
