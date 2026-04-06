"""Tool functions de Bitbucket para el orquestador SOMER.

Cada función es async, recibe parámetros tipados y retorna un dict.
Se importan y registran mediante register_tools.py.

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_RULES_PATH = os.path.join(
    os.path.dirname(__file__), "review_rules.json"
)
_DEFAULT_PHONE = "593995466833"
_REPOS_CONFIG_PATH = Path(__file__).parent / "repos_config.json"


def _load_repos_config() -> Dict[str, Any]:
    """Carga la configuracion de repositorios multiples."""
    if not _REPOS_CONFIG_PATH.is_file():
        return {}
    try:
        with open(_REPOS_CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Error al cargar repos_config.json: %s", exc)
        return {}


def _save_repos_config(config: Dict[str, Any]) -> None:
    """Guarda la configuracion de repositorios."""
    with open(_REPOS_CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)


def _get_workspace() -> str:
    """Obtiene el workspace por defecto de la config o variables de entorno."""
    config = _load_repos_config()
    default_ws = config.get("default_workspace", "")
    return default_ws or os.environ.get("BITBUCKET_WORKSPACE", "")


def _get_default_repo() -> str:
    """Obtiene el repo por defecto del primer repo activo en la config."""
    config = _load_repos_config()
    repos = config.get("repositories", [])
    for r in repos:
        if r.get("active", True):
            return r.get("repo_slug", "")
    return ""


def _get_credentials_key_for_repo(workspace: str, repo: str) -> Optional[str]:
    """Busca la credentials_key configurada para un workspace/repo."""
    config = _load_repos_config()
    for r in config.get("repositories", []):
        if r.get("workspace") == workspace and r.get("repo_slug") == repo:
            return r.get("credentials_key", config.get("default_credentials"))
    return config.get("default_credentials")


async def bb_list_prs(
    workspace: str, repo: str, state: str = "OPEN"
) -> dict:
    """Lista Pull Requests de un repositorio en Bitbucket.

    Args:
        workspace: Slug del workspace de Bitbucket.
        repo: Slug del repositorio.
        state: Estado de los PRs a listar (OPEN, MERGED, DECLINED, SUPERSEDED).

    Returns:
        Dict con la lista de PRs o error.
    """
    from skills.bitbucket.scripts.pr_reviewer import PRReviewer

    workspace = workspace or _get_workspace()
    repo = repo or _get_default_repo()
    if not workspace or not repo:
        return {
            "success": False,
            "error": "Se requieren workspace y repo.",
        }

    creds_key = _get_credentials_key_for_repo(workspace, repo)
    reviewer = PRReviewer(credentials_key=creds_key)
    try:
        prs = await reviewer.list_prs(workspace, repo, state)
        return {
            "success": True,
            "workspace": workspace,
            "repo": repo,
            "state": state,
            "count": len(prs),
            "pull_requests": prs,
        }
    except Exception as exc:
        logger.error("Error al listar PRs: %s", exc)
        return {"success": False, "error": str(exc)}
    finally:
        await reviewer.close()


async def bb_review_pr(
    workspace: str,
    repo: str,
    pr_id: int,
    rules_path: Optional[str] = None,
    auto_action: bool = True,
    notify_phone: Optional[str] = None,
) -> dict:
    """Revisa un Pull Request contra las reglas de validación configuradas.

    Si auto_action=True, aprueba el PR cuando todas las reglas pasan,
    lo rechaza si hay violaciones críticas, o solo comenta si hay advertencias.
    Envía notificación WhatsApp si notify_phone está configurado y el PR tiene problemas.

    Args:
        workspace: Slug del workspace de Bitbucket.
        repo: Slug del repositorio.
        pr_id: ID numérico del Pull Request.
        rules_path: Ruta al archivo JSON de reglas (None = reglas por defecto).
        auto_action: Si True, aprueba/rechaza automáticamente.
        notify_phone: Número de teléfono para notificación WhatsApp (None = no notificar).

    Returns:
        Dict con el resultado de la revisión.
    """
    from skills.bitbucket.scripts.pr_reviewer import PRReviewer

    workspace = workspace or _get_workspace()
    repo = repo or _get_default_repo()
    if not workspace or not repo:
        return {"success": False, "error": "Se requieren workspace y repo."}

    effective_rules = rules_path or _DEFAULT_RULES_PATH
    effective_phone = notify_phone or _DEFAULT_PHONE
    creds_key = _get_credentials_key_for_repo(workspace, repo)

    reviewer = PRReviewer(rules_path=effective_rules, credentials_key=creds_key)
    try:
        result = await reviewer.review_pr(
            workspace, repo, pr_id,
            auto_action=auto_action,
            notify_phone=effective_phone if auto_action else None,
        )
        output = result.to_dict()
        output["success"] = result.error is None
        return output
    except Exception as exc:
        logger.error("Error al revisar PR #%d: %s", pr_id, exc)
        return {"success": False, "error": str(exc)}
    finally:
        await reviewer.close()


async def bb_review_all_prs(
    workspace: str = "",
    repo: str = "",
    rules_path: Optional[str] = None,
    auto_action: bool = True,
    notify_phone: Optional[str] = None,
    all_repos: bool = False,
) -> dict:
    """Revisa TODOS los Pull Requests abiertos de un repositorio o de todos los repos configurados.

    Si all_repos=True, ignora workspace/repo y revisa todos los repos activos
    de repos_config.json. Cada repo usa sus propias credenciales y notify_phones.

    Args:
        workspace: Slug del workspace de Bitbucket (ignorado si all_repos=True).
        repo: Slug del repositorio (ignorado si all_repos=True).
        rules_path: Ruta al archivo JSON de reglas (None = reglas por defecto).
        auto_action: Si True, aprueba/rechaza automaticamente.
        notify_phone: Numero de telefono para notificacion WhatsApp (None = no notificar).
        all_repos: Si True, revisa todos los repos activos configurados.

    Returns:
        Dict con los resultados de todas las revisiones.
    """
    from skills.bitbucket.scripts.pr_reviewer import PRReviewer

    effective_rules = rules_path or _DEFAULT_RULES_PATH

    # Modo all_repos: revisar todos los repos configurados
    if all_repos:
        repo_results = await PRReviewer.review_all_repos(
            rules_path=effective_rules,
            auto_action=auto_action,
        )
        total_reviewed = sum(r.get("total_reviewed", 0) for r in repo_results if r.get("success"))
        total_approved = sum(r.get("approved", 0) for r in repo_results if r.get("success"))
        total_declined = sum(r.get("declined", 0) for r in repo_results if r.get("success"))
        total_warnings = sum(r.get("warnings", 0) for r in repo_results if r.get("success"))

        return {
            "success": True,
            "all_repos": True,
            "repos_reviewed": len([r for r in repo_results if r.get("success")]),
            "repos_failed": len([r for r in repo_results if not r.get("success")]),
            "total_prs_reviewed": total_reviewed,
            "total_approved": total_approved,
            "total_declined": total_declined,
            "total_warnings": total_warnings,
            "per_repo": repo_results,
        }

    # Modo single repo
    workspace = workspace or _get_workspace()
    repo = repo or _get_default_repo()
    if not workspace or not repo:
        return {"success": False, "error": "Se requieren workspace y repo."}

    effective_phone = notify_phone or _DEFAULT_PHONE
    creds_key = _get_credentials_key_for_repo(workspace, repo)

    reviewer = PRReviewer(rules_path=effective_rules, credentials_key=creds_key)
    try:
        results = await reviewer.review_all_prs(
            workspace, repo,
            auto_action=auto_action,
            notify_phone=effective_phone if auto_action else None,
        )
        summaries = [r.to_dict() for r in results]
        approved = sum(1 for r in results if r.passed)
        declined = sum(1 for r in results if r.has_critical)
        warned = sum(1 for r in results if r.has_warnings and not r.has_critical)

        return {
            "success": True,
            "workspace": workspace,
            "repo": repo,
            "total_reviewed": len(results),
            "approved": approved,
            "declined": declined,
            "warnings": warned,
            "results": summaries,
        }
    except Exception as exc:
        logger.error("Error al revisar PRs: %s", exc)
        return {"success": False, "error": str(exc)}
    finally:
        await reviewer.close()


async def bb_get_pr_diff(
    workspace: str, repo: str, pr_id: int
) -> dict:
    """Obtiene el diff (diferencias de código) de un Pull Request.

    Args:
        workspace: Slug del workspace de Bitbucket.
        repo: Slug del repositorio.
        pr_id: ID numérico del Pull Request.

    Returns:
        Dict con el diff como texto o error.
    """
    from skills.bitbucket.scripts.pr_reviewer import PRReviewer

    workspace = workspace or _get_workspace()
    repo = repo or _get_default_repo()
    if not workspace or not repo:
        return {"success": False, "error": "Se requieren workspace y repo."}

    creds_key = _get_credentials_key_for_repo(workspace, repo)
    reviewer = PRReviewer(credentials_key=creds_key)
    try:
        diff = await reviewer.get_pr_diff(workspace, repo, pr_id)
        # Truncar si es muy largo para el contexto del agente
        max_len = 15000
        truncated = len(diff) > max_len
        return {
            "success": True,
            "pr_id": pr_id,
            "diff": diff[:max_len],
            "truncated": truncated,
            "total_length": len(diff),
        }
    except Exception as exc:
        logger.error("Error al obtener diff del PR #%d: %s", pr_id, exc)
        return {"success": False, "error": str(exc)}
    finally:
        await reviewer.close()


async def bb_add_repo(
    workspace: str,
    repo_slug: str,
    label: str = "",
    credentials_key: str = "",
    notify_phones: Optional[List[str]] = None,
    active: bool = True,
) -> dict:
    """Agrega un nuevo repositorio a la configuracion de repos_config.json.

    Args:
        workspace: Slug del workspace de Bitbucket.
        repo_slug: Slug del repositorio.
        label: Nombre descriptivo del repo (opcional).
        credentials_key: Clave de credenciales a usar (opcional, usa default).
        notify_phones: Lista de telefonos para notificaciones (opcional).
        active: Si el repo esta activo para revisiones automaticas.

    Returns:
        Dict con el resultado de la operacion.
    """
    if not workspace or not repo_slug:
        return {"success": False, "error": "Se requieren workspace y repo_slug."}

    config = _load_repos_config()
    if not config:
        config = {
            "default_workspace": workspace,
            "default_credentials": credentials_key or "default",
            "credentials": {},
            "repositories": [],
        }

    # Verificar si ya existe
    repos = config.get("repositories", [])
    for r in repos:
        if r.get("workspace") == workspace and r.get("repo_slug") == repo_slug:
            return {
                "success": False,
                "error": f"El repositorio {workspace}/{repo_slug} ya esta configurado.",
            }

    new_repo = {
        "workspace": workspace,
        "repo_slug": repo_slug,
        "label": label or repo_slug,
        "credentials_key": credentials_key or config.get("default_credentials", "default"),
        "rules_override": {},
        "notify_phones": notify_phones or [],
        "active": active,
    }
    repos.append(new_repo)
    config["repositories"] = repos

    try:
        _save_repos_config(config)
        logger.info("Repositorio %s/%s agregado a la configuracion", workspace, repo_slug)
        return {
            "success": True,
            "message": f"Repositorio {workspace}/{repo_slug} agregado correctamente.",
            "repo": new_repo,
            "total_repos": len(repos),
        }
    except Exception as exc:
        logger.error("Error al guardar repos_config.json: %s", exc)
        return {"success": False, "error": str(exc)}


async def bb_list_repos() -> dict:
    """Lista todos los repositorios configurados en repos_config.json.

    Returns:
        Dict con la lista de repositorios y sus estados.
    """
    config = _load_repos_config()
    if not config:
        return {
            "success": True,
            "count": 0,
            "repositories": [],
            "message": "No hay repositorios configurados. Use bb_add_repo para agregar uno.",
        }

    repos = config.get("repositories", [])
    credentials = config.get("credentials", {})

    repo_list = []
    for r in repos:
        creds_key = r.get("credentials_key", "")
        creds_label = credentials.get(creds_key, {}).get("label", creds_key)
        repo_list.append({
            "workspace": r.get("workspace", ""),
            "repo_slug": r.get("repo_slug", ""),
            "label": r.get("label", ""),
            "credentials": creds_label,
            "notify_phones": r.get("notify_phones", []),
            "active": r.get("active", True),
        })

    return {
        "success": True,
        "default_workspace": config.get("default_workspace", ""),
        "default_credentials": config.get("default_credentials", ""),
        "count": len(repo_list),
        "repositories": repo_list,
    }


async def bb_set_review_rules(rules: dict) -> dict:
    """Actualiza la configuración de reglas de revisión.

    Recibe un dict parcial o completo con las reglas a actualizar.
    Las reglas no especificadas mantienen su valor actual.

    Args:
        rules: Dict con las reglas a actualizar. Estructura:
            {"rules": {"max_files_changed": {"enabled": true, "value": 30}, ...}}

    Returns:
        Dict con la configuración actualizada o error.
    """
    try:
        # Leer reglas actuales
        with open(_DEFAULT_RULES_PATH, "r", encoding="utf-8") as fh:
            current = json.load(fh)

        # Merge: las nuevas reglas sobreescriben las existentes
        new_rules = rules.get("rules", rules)
        if "rules" in current:
            for rule_name, rule_config in new_rules.items():
                if rule_name in current["rules"]:
                    current["rules"][rule_name].update(rule_config)
                else:
                    current["rules"][rule_name] = rule_config
        else:
            current["rules"] = new_rules

        # Guardar
        with open(_DEFAULT_RULES_PATH, "w", encoding="utf-8") as fh:
            json.dump(current, fh, indent=2, ensure_ascii=False)

        logger.info("Reglas de revisión actualizadas")
        return {
            "success": True,
            "message": "Reglas actualizadas correctamente.",
            "rules": current["rules"],
        }
    except Exception as exc:
        logger.error("Error al actualizar reglas: %s", exc)
        return {"success": False, "error": str(exc)}
