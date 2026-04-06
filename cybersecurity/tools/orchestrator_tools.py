"""Tools del orquestador de pentesting — plan, recon, scan, exploit, evidence, report."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from agents.tools.registry import ToolDefinition, ToolRegistry, ToolSection

logger = logging.getLogger(__name__)

_MAX_RESPONSE = 8000


def _truncate(text: str, max_len: int = _MAX_RESPONSE) -> str:
    if len(text) > max_len:
        return text[:max_len] + "\n...(truncado)"
    return text


async def _pentest_plan_handler(args: Dict[str, Any]) -> str:
    """Genera plan de engagement de pentesting."""
    from cybersecurity.orchestrator import PentestOrchestrator

    url = args.get("url", "")
    scope = args.get("scope", "full")
    if not url:
        return "Error: url es requerida"

    orch = PentestOrchestrator()
    plan = orch.plan_engagement(url, scope)
    return plan.model_dump_json(indent=2)


async def _pentest_recon_handler(args: Dict[str, Any]) -> str:
    """Ejecuta fase de reconocimiento."""
    from cybersecurity.orchestrator import PentestOrchestrator
    from cybersecurity.types import PentestPlan

    plan_data = args.get("plan_data")
    if not plan_data:
        return "Error: plan_data es requerido (JSON del plan)"

    try:
        if isinstance(plan_data, str):
            plan_data = json.loads(plan_data)
        plan = PentestPlan.model_validate(plan_data)
    except Exception as exc:
        return f"Error parseando plan: {str(exc)[:200]}"

    orch = PentestOrchestrator()
    result = await orch.run_recon(plan)

    # Guardar resultado en el plan
    plan.phase_results[result.phase.value] = result
    return _truncate(result.model_dump_json(indent=2))


async def _pentest_scan_handler(args: Dict[str, Any]) -> str:
    """Ejecuta fase de escaneo de vulnerabilidades."""
    from cybersecurity.orchestrator import PentestOrchestrator
    from cybersecurity.types import PentestPlan

    plan_data = args.get("plan_data")
    recon_data = args.get("recon_data")
    if not plan_data:
        return "Error: plan_data es requerido"

    try:
        if isinstance(plan_data, str):
            plan_data = json.loads(plan_data)
        plan = PentestPlan.model_validate(plan_data)
    except Exception as exc:
        return f"Error parseando plan: {str(exc)[:200]}"

    orch = PentestOrchestrator()
    result = await orch.run_scan(plan, recon_data)
    return _truncate(result.model_dump_json(indent=2))


async def _pentest_exploit_handler(args: Dict[str, Any]) -> str:
    """Ejecuta fase de explotación."""
    from cybersecurity.orchestrator import PentestOrchestrator
    from cybersecurity.types import PentestPlan

    plan_data = args.get("plan_data")
    scan_data = args.get("scan_data")
    if not plan_data:
        return "Error: plan_data es requerido"

    try:
        if isinstance(plan_data, str):
            plan_data = json.loads(plan_data)
        plan = PentestPlan.model_validate(plan_data)
    except Exception as exc:
        return f"Error parseando plan: {str(exc)[:200]}"

    orch = PentestOrchestrator()
    result = await orch.run_exploits(plan, scan_data)
    return _truncate(result.model_dump_json(indent=2))


async def _pentest_evidence_handler(args: Dict[str, Any]) -> str:
    """Captura evidencia y genera paquete."""
    from cybersecurity.orchestrator import PentestOrchestrator
    from cybersecurity.types import PentestPlan

    plan_data = args.get("plan_data")
    exploit_data = args.get("exploit_data")
    if not plan_data:
        return "Error: plan_data es requerido"

    try:
        if isinstance(plan_data, str):
            plan_data = json.loads(plan_data)
        plan = PentestPlan.model_validate(plan_data)
    except Exception as exc:
        return f"Error parseando plan: {str(exc)[:200]}"

    orch = PentestOrchestrator()
    result = await orch.run_evidence(plan, exploit_data)
    return _truncate(result.model_dump_json(indent=2))


async def _pentest_report_handler(args: Dict[str, Any]) -> str:
    """Genera reporte final consolidado."""
    from cybersecurity.orchestrator import PentestOrchestrator
    from cybersecurity.types import PentestPlan, PhaseResult

    plan_data = args.get("plan_data")
    if not plan_data:
        return "Error: plan_data es requerido"

    try:
        if isinstance(plan_data, str):
            plan_data = json.loads(plan_data)
        plan = PentestPlan.model_validate(plan_data)
    except Exception as exc:
        return f"Error parseando plan: {str(exc)[:200]}"

    orch = PentestOrchestrator()
    md = orch.generate_final_report(plan)

    return json.dumps({
        "format": "md",
        "content": _truncate(md),
        "workspace_path": plan.workspace_path,
    })


async def _full_pentest_handler(args: Dict[str, Any]) -> str:
    """Ejecuta el pipeline COMPLETO de pentesting: plan → recon → scan → exploit → evidence → report.

    Una sola llamada que ejecuta todas las fases automáticamente.
    """
    from cybersecurity.orchestrator import PentestOrchestrator

    url = args.get("url", "")
    scope = args.get("scope", "full")
    if not url:
        return "Error: url es requerida"

    orch = PentestOrchestrator()

    # Paso 1: Plan
    logger.info("[PENTEST] Fase 1/5: Plan para %s (scope=%s)", url, scope)
    plan = orch.plan_engagement(url, scope)

    # Paso 2: Recon
    logger.info("[PENTEST] Fase 2/5: Reconocimiento")
    recon_result = await orch.run_recon(plan)
    plan.phase_results[recon_result.phase.value] = recon_result
    recon_data = recon_result.data if recon_result.success else None

    # Paso 3: Scan
    logger.info("[PENTEST] Fase 3/5: Escaneo de vulnerabilidades")
    scan_result = await orch.run_scan(plan, recon_data)
    plan.phase_results[scan_result.phase.value] = scan_result
    scan_data = scan_result.data if scan_result.success else None

    # Paso 4: Exploit (solo si hay findings en scan)
    if scope != "recon-only" and scan_data:
        logger.info("[PENTEST] Fase 4/5: Explotación (PoC)")
        exploit_result = await orch.run_exploits(plan, scan_data)
        plan.phase_results[exploit_result.phase.value] = exploit_result
        exploit_data = exploit_result.data if exploit_result.success else None

        # Paso 5: Evidence
        logger.info("[PENTEST] Fase 5/5: Evidencia")
        try:
            evidence_result = await orch.run_evidence(plan, exploit_data)
            plan.phase_results[evidence_result.phase.value] = evidence_result
        except Exception as exc:
            logger.warning("[PENTEST] Evidence fase falló (no crítico): %s", exc)

    # Reporte final
    logger.info("[PENTEST] Generando reporte final")
    report_md = orch.generate_final_report(plan)

    # Resumen compacto para el LLM
    summary = {
        "target": url,
        "scope": scope,
        "workspace": plan.workspace_path,
        "phases_completed": list(plan.phase_results.keys()),
        "total_findings": sum(
            r.findings_count for r in plan.phase_results.values()
        ),
        "critical_findings": [],
        "report_preview": report_md[:3000],
    }

    # Extraer findings críticos/altos para el resumen
    for phase_key, phase_result in plan.phase_results.items():
        if phase_result.data:
            for f in phase_result.data.get("all_findings", []):
                sev = f.get("severity", "")
                if sev in ("critical", "high"):
                    summary["critical_findings"].append({
                        "title": f.get("title", ""),
                        "severity": sev,
                        "category": f.get("category", ""),
                    })

    return _truncate(json.dumps(summary, indent=2, ensure_ascii=False), 12000)


def register_orchestrator_tools(registry: ToolRegistry) -> None:
    """Registra las tools del orquestador en el registry."""

    # ── Tool principal: pipeline completo en una sola llamada ──
    registry.register(ToolDefinition(
        id="full_pentest",
        name="full_pentest",
        description=(
            "Ejecuta un pentest COMPLETO automáticamente: "
            "plan → reconocimiento → escaneo de vulnerabilidades → "
            "explotación (PoC) → evidencia → reporte. "
            "Una sola llamada ejecuta todas las fases. "
            "USA ESTA HERRAMIENTA cuando el usuario pida revisar "
            "vulnerabilidades, auditoría de seguridad, o pentest de un sitio."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL del sitio web a escanear",
                },
                "scope": {
                    "type": "string",
                    "enum": ["full", "quick", "recon-only"],
                    "description": "Alcance: full (todas las fases), quick (sin exploits), recon-only",
                },
            },
            "required": ["url"],
        },
        handler=_full_pentest_handler,
        section=ToolSection.SECURITY,
        timeout_secs=600,  # 10 minutos para pipelines de pentesting
    ))

    # ── Tools individuales por fase (para control granular) ──
    registry.register(ToolDefinition(
        id="pentest_plan",
        name="pentest_plan",
        description=(
            "Genera un plan de engagement de pentesting para una URL. "
            "Crea el workspace y define las fases a ejecutar."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL del target",
                },
                "scope": {
                    "type": "string",
                    "enum": ["full", "quick", "recon-only"],
                    "description": "Alcance del pentest (default: full)",
                },
            },
            "required": ["url"],
        },
        handler=_pentest_plan_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30.0,
    ))

    registry.register(ToolDefinition(
        id="pentest_recon",
        name="pentest_recon",
        description=(
            "Ejecuta la fase de reconocimiento de un pentest. "
            "Incluye: tecnologías, DNS, puertos, subdominios y detección de WAF."
        ),
        parameters={
            "type": "object",
            "properties": {
                "plan_data": {
                    "type": "object",
                    "description": "JSON del plan generado por pentest_plan",
                },
            },
            "required": ["plan_data"],
        },
        handler=_pentest_recon_handler,
        section=ToolSection.SECURITY,
        timeout_secs=120.0,
    ))

    registry.register(ToolDefinition(
        id="pentest_scan",
        name="pentest_scan",
        description=(
            "Ejecuta la fase de escaneo de vulnerabilidades. "
            "Incluye 18 checks estándar + 10 scanners avanzados "
            "(SQLi, SSTI, path traversal, JWT, etc.)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "plan_data": {
                    "type": "object",
                    "description": "JSON del plan",
                },
                "recon_data": {
                    "type": "object",
                    "description": "Datos de la fase de recon (opcional)",
                },
            },
            "required": ["plan_data"],
        },
        handler=_pentest_scan_handler,
        section=ToolSection.SECURITY,
        timeout_secs=300.0,
    ))

    registry.register(ToolDefinition(
        id="pentest_exploit",
        name="pentest_exploit",
        description=(
            "Ejecuta la fase de explotación con PoC seguros. "
            "Incluye 14 exploits originales + 10 exploits avanzados."
        ),
        parameters={
            "type": "object",
            "properties": {
                "plan_data": {
                    "type": "object",
                    "description": "JSON del plan",
                },
                "scan_data": {
                    "type": "object",
                    "description": "Datos de la fase de scan",
                },
            },
            "required": ["plan_data"],
        },
        handler=_pentest_exploit_handler,
        section=ToolSection.SECURITY,
        timeout_secs=300.0,
    ))

    registry.register(ToolDefinition(
        id="pentest_evidence",
        name="pentest_evidence",
        description=(
            "Captura evidencia completa: screenshots, cadena de evidencia "
            "y paquete ZIP exportable."
        ),
        parameters={
            "type": "object",
            "properties": {
                "plan_data": {
                    "type": "object",
                    "description": "JSON del plan",
                },
                "exploit_data": {
                    "type": "object",
                    "description": "Datos de la fase de exploit",
                },
            },
            "required": ["plan_data"],
        },
        handler=_pentest_evidence_handler,
        section=ToolSection.SECURITY,
        timeout_secs=120.0,
    ))

    registry.register(ToolDefinition(
        id="pentest_report",
        name="pentest_report",
        description=(
            "Genera el reporte final consolidado de pentesting en Markdown. "
            "Incluye resumen de fases, findings y evidencia."
        ),
        parameters={
            "type": "object",
            "properties": {
                "plan_data": {
                    "type": "object",
                    "description": "JSON del plan con resultados de fases",
                },
            },
            "required": ["plan_data"],
        },
        handler=_pentest_report_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30.0,
    ))
