"""Registro de tools de Bitbucket PR Review para el sistema SOMER.

Expone register_bitbucket_tools() que registra las herramientas
en el ToolRegistry del agente, siguiendo el patrón de
agents/tools/shell_tools.py y agents/tools/business_tools.py.

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from agents.tools.registry import (
    ToolDefinition,
    ToolProfile,
    ToolRegistry,
    ToolSection,
)

logger = logging.getLogger(__name__)


# ── Handlers (wrappers que adaptan dict args → tool functions) ──


async def _handle_bb_list_prs(args: Dict[str, Any]) -> str:
    from skills.bitbucket.scripts.bb_tools import bb_list_prs

    result = await bb_list_prs(
        workspace=args.get("workspace", ""),
        repo=args.get("repo", ""),
        state=args.get("state", "OPEN"),
    )
    return json.dumps(result, indent=2, ensure_ascii=False)


async def _handle_bb_review_pr(args: Dict[str, Any]) -> str:
    from skills.bitbucket.scripts.bb_tools import bb_review_pr

    result = await bb_review_pr(
        workspace=args.get("workspace", ""),
        repo=args.get("repo", ""),
        pr_id=int(args.get("pr_id", 0)),
        rules_path=args.get("rules_path"),
        auto_action=args.get("auto_action", True),
        notify_phone=args.get("notify_phone"),
    )
    return json.dumps(result, indent=2, ensure_ascii=False)


async def _handle_bb_review_all_prs(args: Dict[str, Any]) -> str:
    from skills.bitbucket.scripts.bb_tools import bb_review_all_prs

    result = await bb_review_all_prs(
        workspace=args.get("workspace", ""),
        repo=args.get("repo", ""),
        rules_path=args.get("rules_path"),
        auto_action=args.get("auto_action", True),
        notify_phone=args.get("notify_phone"),
        all_repos=args.get("all_repos", False),
    )
    return json.dumps(result, indent=2, ensure_ascii=False)


async def _handle_bb_get_pr_diff(args: Dict[str, Any]) -> str:
    from skills.bitbucket.scripts.bb_tools import bb_get_pr_diff

    result = await bb_get_pr_diff(
        workspace=args.get("workspace", ""),
        repo=args.get("repo", ""),
        pr_id=int(args.get("pr_id", 0)),
    )
    return json.dumps(result, indent=2, ensure_ascii=False)


async def _handle_bb_add_repo(args: Dict[str, Any]) -> str:
    from skills.bitbucket.scripts.bb_tools import bb_add_repo

    result = await bb_add_repo(
        workspace=args.get("workspace", ""),
        repo_slug=args.get("repo_slug", ""),
        label=args.get("label", ""),
        credentials_key=args.get("credentials_key", ""),
        notify_phones=args.get("notify_phones"),
        active=args.get("active", True),
    )
    return json.dumps(result, indent=2, ensure_ascii=False)


async def _handle_bb_list_repos(args: Dict[str, Any]) -> str:
    from skills.bitbucket.scripts.bb_tools import bb_list_repos

    result = await bb_list_repos()
    return json.dumps(result, indent=2, ensure_ascii=False)


async def _handle_bb_set_review_rules(args: Dict[str, Any]) -> str:
    from skills.bitbucket.scripts.bb_tools import bb_set_review_rules

    result = await bb_set_review_rules(rules=args.get("rules", {}))
    return json.dumps(result, indent=2, ensure_ascii=False)


# ── Registro ─────────────────────────────────────────────────


def register_bitbucket_tools(registry: ToolRegistry) -> None:
    """Registra las herramientas de Bitbucket PR Review en el registry.

    Tools registradas:
        - bb_list_prs: Listar PRs de un repositorio
        - bb_review_pr: Revisar un PR contra reglas configurables
        - bb_review_all_prs: Revisar todos los PRs abiertos
        - bb_get_pr_diff: Obtener el diff de un PR
        - bb_set_review_rules: Actualizar configuración de reglas
    """

    # ── bb_list_prs ──────────────────────────────────────────

    registry.register(ToolDefinition(
        id="bb_list_prs",
        name="bb_list_prs",
        description=(
            "Lista Pull Requests de un repositorio en Bitbucket. "
            "Usar para: ver PRs abiertos, buscar PRs por estado, "
            "obtener resumen de actividad de PRs en un repo."
        ),
        parameters={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Slug del workspace de Bitbucket.",
                },
                "repo": {
                    "type": "string",
                    "description": "Slug del repositorio.",
                },
                "state": {
                    "type": "string",
                    "description": "Estado de los PRs: OPEN, MERGED, DECLINED, SUPERSEDED (default: OPEN).",
                    "enum": ["OPEN", "MERGED", "DECLINED", "SUPERSEDED"],
                    "default": "OPEN",
                },
            },
            "required": ["workspace", "repo"],
        },
        handler=_handle_bb_list_prs,
        section=ToolSection.BUSINESS,
        profiles=[ToolProfile.CODING, ToolProfile.FULL],
        timeout_secs=60.0,
    ))

    # ── bb_review_pr ─────────────────────────────────────────

    registry.register(ToolDefinition(
        id="bb_review_pr",
        name="bb_review_pr",
        description=(
            "Revisa un Pull Request de Bitbucket contra reglas de validación configurables. "
            "Evalúa tamaño del PR, patrones prohibidos, convenciones de nombres, etc. "
            "Si auto_action=true, aprueba el PR cuando todo pasa, lo rechaza si hay errores "
            "críticos, o solo comenta si hay advertencias. Envía notificación WhatsApp "
            "cuando hay problemas."
        ),
        parameters={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Slug del workspace de Bitbucket.",
                },
                "repo": {
                    "type": "string",
                    "description": "Slug del repositorio.",
                },
                "pr_id": {
                    "type": "integer",
                    "description": "ID numérico del Pull Request a revisar.",
                },
                "rules_path": {
                    "type": "string",
                    "description": "Ruta al archivo JSON de reglas (opcional, usa reglas por defecto si no se especifica).",
                },
                "auto_action": {
                    "type": "boolean",
                    "description": "Si true, aprueba/rechaza automáticamente según resultado (default: true).",
                    "default": True,
                },
                "notify_phone": {
                    "type": "string",
                    "description": "Número de teléfono para notificación WhatsApp (opcional).",
                },
            },
            "required": ["workspace", "repo", "pr_id"],
        },
        handler=_handle_bb_review_pr,
        section=ToolSection.BUSINESS,
        profiles=[ToolProfile.CODING, ToolProfile.FULL],
        timeout_secs=120.0,
    ))

    # ── bb_review_all_prs ────────────────────────────────────

    registry.register(ToolDefinition(
        id="bb_review_all_prs",
        name="bb_review_all_prs",
        description=(
            "Revisa TODOS los Pull Requests abiertos de un repositorio en Bitbucket. "
            "Evalua cada PR contra las reglas de validacion y ejecuta las acciones "
            "correspondientes. Con all_repos=true revisa TODOS los repos activos "
            "configurados en repos_config.json. Util para revisiones periodicas (cron)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Slug del workspace de Bitbucket (opcional si all_repos=true, usa default de config).",
                },
                "repo": {
                    "type": "string",
                    "description": "Slug del repositorio (opcional si all_repos=true, usa default de config).",
                },
                "rules_path": {
                    "type": "string",
                    "description": "Ruta al archivo JSON de reglas (opcional).",
                },
                "auto_action": {
                    "type": "boolean",
                    "description": "Si true, aprueba/rechaza automaticamente (default: true).",
                    "default": True,
                },
                "notify_phone": {
                    "type": "string",
                    "description": "Numero de telefono para notificacion WhatsApp (opcional).",
                },
                "all_repos": {
                    "type": "boolean",
                    "description": (
                        "Si true, revisa TODOS los repositorios activos configurados "
                        "en repos_config.json, ignorando workspace y repo. (default: false)."
                    ),
                    "default": False,
                },
            },
            "required": [],
        },
        handler=_handle_bb_review_all_prs,
        section=ToolSection.BUSINESS,
        profiles=[ToolProfile.CODING, ToolProfile.FULL],
        timeout_secs=300.0,
    ))

    # ── bb_get_pr_diff ───────────────────────────────────────

    registry.register(ToolDefinition(
        id="bb_get_pr_diff",
        name="bb_get_pr_diff",
        description=(
            "Obtiene el diff (diferencias de código) de un Pull Request en Bitbucket. "
            "Usar para: inspeccionar cambios de código, analizar modificaciones antes de "
            "aprobar, revisar archivos afectados."
        ),
        parameters={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Slug del workspace de Bitbucket.",
                },
                "repo": {
                    "type": "string",
                    "description": "Slug del repositorio.",
                },
                "pr_id": {
                    "type": "integer",
                    "description": "ID numérico del Pull Request.",
                },
            },
            "required": ["workspace", "repo", "pr_id"],
        },
        handler=_handle_bb_get_pr_diff,
        section=ToolSection.BUSINESS,
        profiles=[ToolProfile.CODING, ToolProfile.FULL],
        timeout_secs=60.0,
    ))

    # ── bb_set_review_rules ──────────────────────────────────

    registry.register(ToolDefinition(
        id="bb_set_review_rules",
        name="bb_set_review_rules",
        description=(
            "Actualiza la configuración de reglas de revisión de PRs. "
            "Permite habilitar/deshabilitar reglas, cambiar umbrales, "
            "agregar patrones prohibidos, etc. Los cambios se persisten "
            "en el archivo review_rules.json."
        ),
        parameters={
            "type": "object",
            "properties": {
                "rules": {
                    "type": "object",
                    "description": (
                        "Dict con las reglas a actualizar. Ejemplo: "
                        '{"max_files_changed": {"enabled": true, "value": 30}, '
                        '"forbidden_patterns": {"patterns": ["console\\\\.log"]}}. '
                        "Solo las reglas especificadas se actualizan; las demás mantienen su valor."
                    ),
                },
            },
            "required": ["rules"],
        },
        handler=_handle_bb_set_review_rules,
        section=ToolSection.BUSINESS,
        profiles=[ToolProfile.CODING, ToolProfile.FULL],
        timeout_secs=10.0,
    ))

    # ── bb_add_repo ───────────────────────────────────────────

    registry.register(ToolDefinition(
        id="bb_add_repo",
        name="bb_add_repo",
        description=(
            "Agrega un nuevo repositorio a la configuracion multi-repo de Bitbucket. "
            "El repo se guarda en repos_config.json y queda disponible para "
            "revisiones automaticas con bb_review_all_prs(all_repos=true)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Slug del workspace de Bitbucket.",
                },
                "repo_slug": {
                    "type": "string",
                    "description": "Slug del repositorio.",
                },
                "label": {
                    "type": "string",
                    "description": "Nombre descriptivo del repositorio (opcional).",
                },
                "credentials_key": {
                    "type": "string",
                    "description": (
                        "Clave de credenciales a usar (e.g. 'sukasa'). "
                        "Busca BITBUCKET_APP_PASSWORD_{KEY} en env. "
                        "Si no se especifica, usa la credencial por defecto."
                    ),
                },
                "notify_phones": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de telefonos para notificaciones WhatsApp (opcional).",
                },
                "active": {
                    "type": "boolean",
                    "description": "Si el repo esta activo para revisiones automaticas (default: true).",
                    "default": True,
                },
            },
            "required": ["workspace", "repo_slug"],
        },
        handler=_handle_bb_add_repo,
        section=ToolSection.BUSINESS,
        profiles=[ToolProfile.CODING, ToolProfile.FULL],
        timeout_secs=10.0,
    ))

    # ── bb_list_repos ───────────────────────────────────────────

    registry.register(ToolDefinition(
        id="bb_list_repos",
        name="bb_list_repos",
        description=(
            "Lista todos los repositorios configurados en repos_config.json. "
            "Muestra workspace, repo, credenciales, telefonos de notificacion "
            "y estado activo/inactivo de cada repositorio."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=_handle_bb_list_repos,
        section=ToolSection.BUSINESS,
        profiles=[ToolProfile.CODING, ToolProfile.FULL],
        timeout_secs=10.0,
    ))

    logger.info("Tools de Bitbucket PR Review registradas (%d tools)", 7)
