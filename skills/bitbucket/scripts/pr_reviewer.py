#!/usr/bin/env python3
"""Revisión automática de Pull Requests en Bitbucket.

Conecta con la API REST 2.0 de Bitbucket, evalúa PRs contra reglas
configurables, publica comentarios, aprueba/rechaza y notifica por WhatsApp.

Uso como CLI:
    python3 pr_reviewer.py review <workspace> <repo> <pr_id> [--rules path] [--auto] [--notify phone]
    python3 pr_reviewer.py review-all <workspace> <repo> [--rules path] [--auto] [--notify phone]
    python3 pr_reviewer.py list <workspace> <repo> [--state OPEN]

Uso como módulo:
    from skills.bitbucket.scripts.pr_reviewer import PRReviewer
    reviewer = PRReviewer(rules_path="review_rules.json")
    result = await reviewer.review_pr("ws", "repo", 42)

Python 3.9+ — requiere aiohttp.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)

# ── Constantes ───────────────────────────────────────────────

_SOMER_ENV = os.path.join(os.path.expanduser("~"), ".somer", ".env")
_DEFAULT_RULES = Path(__file__).parent / "review_rules.json"
_BB_API = "https://api.bitbucket.org/2.0"
_NOTIFY_SCRIPT = "/var/www/somer/notify_wa.py"
_REPOS_CONFIG = Path(__file__).parent / "repos_config.json"


# ── Helpers de entorno ───────────────────────────────────────


def _load_env() -> None:
    """Carga variables de ~/.somer/.env si no están en el entorno."""
    if not os.path.isfile(_SOMER_ENV):
        return
    with open(_SOMER_ENV, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip().strip('"'), value.strip().strip('"')
            if key and key not in os.environ:
                os.environ[key] = value


_load_env()


def _load_repos_config() -> Dict[str, Any]:
    """Carga la configuracion de repositorios desde repos_config.json.

    Returns:
        Dict con la configuracion o un dict vacio si no existe el archivo.
    """
    if not _REPOS_CONFIG.is_file():
        return {}
    try:
        with open(_REPOS_CONFIG, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Error al cargar repos_config.json: %s", exc)
        return {}


def _save_repos_config(config: Dict[str, Any]) -> None:
    """Guarda la configuracion de repositorios en repos_config.json."""
    with open(_REPOS_CONFIG, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)


def _get_auth(credentials_key: Optional[str] = None) -> Tuple[str, str]:
    """Retorna (username, app_password) o lanza error.

    Args:
        credentials_key: Clave de credenciales (e.g. "sukasa").
            Busca BITBUCKET_APP_PASSWORD_{KEY} primero, luego BITBUCKET_APP_PASSWORD.
            Si hay repos_config, usa el username de la credencial configurada.
    """
    config = _load_repos_config()
    creds_config = config.get("credentials", {})

    # Determinar username
    user = ""
    if credentials_key and credentials_key in creds_config:
        user = creds_config[credentials_key].get("username", "")
    if not user:
        user = os.environ.get("BITBUCKET_USERNAME", "")

    # Determinar password: BITBUCKET_APP_PASSWORD_{KEY} -> BITBUCKET_APP_PASSWORD
    passwd = ""
    if credentials_key:
        env_key = f"BITBUCKET_APP_PASSWORD_{credentials_key.upper()}"
        passwd = os.environ.get(env_key, "")
    if not passwd:
        passwd = os.environ.get("BITBUCKET_APP_PASSWORD", "")

    if not user or not passwd:
        raise EnvironmentError(
            "Faltan variables de entorno BITBUCKET_USERNAME y/o BITBUCKET_APP_PASSWORD"
            + (f" (o BITBUCKET_APP_PASSWORD_{credentials_key.upper()})" if credentials_key else "")
            + ". Configurelas en ~/.somer/.env o como variables de entorno."
        )
    return user, passwd


# ── Tipos de resultado ───────────────────────────────────────


@dataclass
class RuleViolation:
    """Una violación de regla detectada."""
    rule: str
    severity: str  # "critical" | "warning" | "info"
    message: str


@dataclass
class ReviewResult:
    """Resultado completo de la revisión de un PR."""
    pr_id: int
    pr_title: str
    repo: str
    workspace: str
    violations: List[RuleViolation] = field(default_factory=list)
    action: str = "none"  # "approved" | "declined" | "commented" | "none"
    comment_posted: bool = False
    notification_sent: bool = False
    error: Optional[str] = None

    @property
    def has_critical(self) -> bool:
        return any(v.severity == "critical" for v in self.violations)

    @property
    def has_warnings(self) -> bool:
        return any(v.severity == "warning" for v in self.violations)

    @property
    def passed(self) -> bool:
        return len(self.violations) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pr_id": self.pr_id,
            "pr_title": self.pr_title,
            "repo": self.repo,
            "workspace": self.workspace,
            "passed": self.passed,
            "has_critical": self.has_critical,
            "has_warnings": self.has_warnings,
            "action": self.action,
            "comment_posted": self.comment_posted,
            "notification_sent": self.notification_sent,
            "violations": [
                {"rule": v.rule, "severity": v.severity, "message": v.message}
                for v in self.violations
            ],
            "error": self.error,
        }


# ── Cliente Bitbucket ────────────────────────────────────────


class BitbucketClient:
    """Cliente async para la API REST 2.0 de Bitbucket."""

    def __init__(self, credentials_key: Optional[str] = None) -> None:
        self._credentials_key = credentials_key
        self._user, self._passwd = _get_auth(credentials_key)
        self._auth = aiohttp.BasicAuth(self._user, self._passwd)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(auth=self._auth)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_json(self, url: str) -> Dict[str, Any]:
        session = await self._get_session()
        async with session.get(url) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(
                    f"Bitbucket API error {resp.status} en GET {url}: {body[:500]}"
                )
            return await resp.json()

    async def _get_text(self, url: str) -> str:
        session = await self._get_session()
        async with session.get(url) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(
                    f"Bitbucket API error {resp.status} en GET {url}: {body[:500]}"
                )
            return await resp.text()

    async def _post_json(
        self, url: str, data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        session = await self._get_session()
        async with session.post(url, json=data) as resp:
            body_text = await resp.text()
            if resp.status not in (200, 201):
                raise RuntimeError(
                    f"Bitbucket API error {resp.status} en POST {url}: {body_text[:500]}"
                )
            if body_text.strip():
                return json.loads(body_text)
            return {"status": "ok"}

    # ── Endpoints ────────────────────────────────────────────

    async def list_prs(
        self, workspace: str, repo: str, state: str = "OPEN"
    ) -> List[Dict[str, Any]]:
        """Lista PRs de un repo (paginado automáticamente)."""
        url = f"{_BB_API}/repositories/{workspace}/{repo}/pullrequests?state={state}&pagelen=50"
        all_prs: List[Dict[str, Any]] = []
        while url:
            data = await self._get_json(url)
            all_prs.extend(data.get("values", []))
            url = data.get("next")
        return all_prs

    async def get_pr(
        self, workspace: str, repo: str, pr_id: int
    ) -> Dict[str, Any]:
        """Obtiene detalle de un PR."""
        url = f"{_BB_API}/repositories/{workspace}/{repo}/pullrequests/{pr_id}"
        return await self._get_json(url)

    async def get_pr_diff(
        self, workspace: str, repo: str, pr_id: int
    ) -> str:
        """Obtiene el diff de un PR como texto."""
        url = f"{_BB_API}/repositories/{workspace}/{repo}/pullrequests/{pr_id}/diff"
        return await self._get_text(url)

    async def get_pr_commits(
        self, workspace: str, repo: str, pr_id: int
    ) -> List[Dict[str, Any]]:
        """Obtiene los commits de un PR."""
        url = f"{_BB_API}/repositories/{workspace}/{repo}/pullrequests/{pr_id}/commits?pagelen=100"
        data = await self._get_json(url)
        return data.get("values", [])

    async def post_comment(
        self, workspace: str, repo: str, pr_id: int, comment: str
    ) -> Dict[str, Any]:
        """Publica un comentario en un PR."""
        url = f"{_BB_API}/repositories/{workspace}/{repo}/pullrequests/{pr_id}/comments"
        return await self._post_json(url, {"content": {"raw": comment}})

    async def approve_pr(
        self, workspace: str, repo: str, pr_id: int
    ) -> Dict[str, Any]:
        """Aprueba un PR."""
        url = f"{_BB_API}/repositories/{workspace}/{repo}/pullrequests/{pr_id}/approve"
        return await self._post_json(url)

    async def decline_pr(
        self, workspace: str, repo: str, pr_id: int
    ) -> Dict[str, Any]:
        """Rechaza un PR."""
        url = f"{_BB_API}/repositories/{workspace}/{repo}/pullrequests/{pr_id}/decline"
        return await self._post_json(url)


# ── Motor de reglas ──────────────────────────────────────────


class RulesEngine:
    """Evalúa un PR contra un conjunto de reglas configurables."""

    def __init__(self, rules_path: Optional[str] = None) -> None:
        path = Path(rules_path) if rules_path else _DEFAULT_RULES
        if not path.is_file():
            raise FileNotFoundError(f"Archivo de reglas no encontrado: {path}")
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.rules: Dict[str, Any] = data.get("rules", data)

    def evaluate(
        self,
        pr: Dict[str, Any],
        diff: str,
        commits: List[Dict[str, Any]],
    ) -> List[RuleViolation]:
        """Evalúa todas las reglas habilitadas contra un PR."""
        violations: List[RuleViolation] = []

        # Extraer info del PR
        source_branch = (
            pr.get("source", {}).get("branch", {}).get("name", "")
        )
        title = pr.get("title", "")
        description = pr.get("description") or ""
        reviewers = pr.get("reviewers", [])

        # Parsear diff para contar archivos y líneas
        files_changed = self._count_files(diff)
        lines_added = self._count_lines_added(diff)
        modified_files = self._extract_modified_files(diff)

        # 1. max_files_changed
        rule = self.rules.get("max_files_changed", {})
        if rule.get("enabled") and files_changed > rule.get("value", 20):
            violations.append(RuleViolation(
                rule="max_files_changed",
                severity=rule.get("severity", "critical"),
                message=rule.get("message", "").format(
                    actual=files_changed, limit=rule["value"]
                ),
            ))

        # 2. max_lines_added
        rule = self.rules.get("max_lines_added", {})
        if rule.get("enabled") and lines_added > rule.get("value", 500):
            violations.append(RuleViolation(
                rule="max_lines_added",
                severity=rule.get("severity", "critical"),
                message=rule.get("message", "").format(
                    actual=lines_added, limit=rule["value"]
                ),
            ))

        # 3. forbidden_patterns
        rule = self.rules.get("forbidden_patterns", {})
        if rule.get("enabled"):
            for pattern in rule.get("patterns", []):
                try:
                    matches = re.findall(pattern, diff)
                    if matches:
                        violations.append(RuleViolation(
                            rule="forbidden_patterns",
                            severity=rule.get("severity", "critical"),
                            message=rule.get("message", "").format(
                                pattern=pattern, count=len(matches)
                            ),
                        ))
                except re.error as e:
                    logger.warning("Regex inválido '%s': %s", pattern, e)

        # 4. required_patterns
        rule = self.rules.get("required_patterns", {})
        if rule.get("enabled"):
            for pattern in rule.get("patterns", []):
                try:
                    if not re.search(pattern, diff):
                        violations.append(RuleViolation(
                            rule="required_patterns",
                            severity=rule.get("severity", "warning"),
                            message=rule.get("message", "").format(
                                pattern=pattern
                            ),
                        ))
                except re.error as e:
                    logger.warning("Regex inválido '%s': %s", pattern, e)

        # 5. forbidden_files
        rule = self.rules.get("forbidden_files", {})
        if rule.get("enabled"):
            forbidden = rule.get("files", [])
            for mod_file in modified_files:
                basename = os.path.basename(mod_file)
                if basename in forbidden or mod_file in forbidden:
                    violations.append(RuleViolation(
                        rule="forbidden_files",
                        severity=rule.get("severity", "critical"),
                        message=rule.get("message", "").format(file=mod_file),
                    ))

        # 6. branch_naming
        rule = self.rules.get("branch_naming", {})
        if rule.get("enabled") and source_branch:
            pattern = rule.get("pattern", "")
            if pattern and not re.match(pattern, source_branch):
                violations.append(RuleViolation(
                    rule="branch_naming",
                    severity=rule.get("severity", "warning"),
                    message=rule.get("message", "").format(branch=source_branch),
                ))

        # 7. title_format
        rule = self.rules.get("title_format", {})
        if rule.get("enabled") and title:
            pattern = rule.get("pattern", "")
            if pattern and not re.match(pattern, title):
                violations.append(RuleViolation(
                    rule="title_format",
                    severity=rule.get("severity", "warning"),
                    message=rule.get("message", "").format(title=title),
                ))

        # 8. require_description
        rule = self.rules.get("require_description", {})
        if rule.get("enabled") and not description.strip():
            violations.append(RuleViolation(
                rule="require_description",
                severity=rule.get("severity", "warning"),
                message=rule.get("message", "El PR no tiene descripción."),
            ))

        # 9. max_commits
        rule = self.rules.get("max_commits", {})
        if rule.get("enabled") and len(commits) > rule.get("value", 10):
            violations.append(RuleViolation(
                rule="max_commits",
                severity=rule.get("severity", "warning"),
                message=rule.get("message", "").format(
                    actual=len(commits), limit=rule["value"]
                ),
            ))

        # 10. require_reviewer
        rule = self.rules.get("require_reviewer", {})
        if rule.get("enabled") and len(reviewers) == 0:
            violations.append(RuleViolation(
                rule="require_reviewer",
                severity=rule.get("severity", "warning"),
                message=rule.get("message", "El PR no tiene revisores asignados."),
            ))

        return violations

    # ── Helpers de diff ──────────────────────────────────────

    @staticmethod
    def _count_files(diff: str) -> int:
        """Cuenta archivos modificados en el diff."""
        return len(re.findall(r"^diff --git", diff, re.MULTILINE))

    @staticmethod
    def _count_lines_added(diff: str) -> int:
        """Cuenta líneas agregadas (que empiezan con +, excluyendo +++).."""
        lines = diff.split("\n")
        count = 0
        for line in lines:
            if line.startswith("+") and not line.startswith("+++"):
                count += 1
        return count

    @staticmethod
    def _extract_modified_files(diff: str) -> List[str]:
        """Extrae nombres de archivos modificados del diff."""
        # Formato: diff --git a/path/file b/path/file
        files = re.findall(r"^diff --git a/(.*?) b/", diff, re.MULTILINE)
        return files


# ── Notificación WhatsApp ────────────────────────────────────


def _send_whatsapp_notification(phone: str, message: str) -> bool:
    """Envía notificación WhatsApp invocando notify_wa.py como subproceso.

    Returns:
        True si el envío fue exitoso, False en caso contrario.
    """
    if not os.path.isfile(_NOTIFY_SCRIPT):
        logger.error("Script de notificación no encontrado: %s", _NOTIFY_SCRIPT)
        return False
    try:
        result = subprocess.run(
            [sys.executable, _NOTIFY_SCRIPT, phone, message],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            logger.info("Notificación WhatsApp enviada a %s", phone)
            return True
        else:
            logger.error(
                "Error al enviar notificación WhatsApp: %s",
                result.stderr.strip(),
            )
            return False
    except subprocess.TimeoutExpired:
        logger.error("Timeout al enviar notificación WhatsApp")
        return False
    except Exception as exc:
        logger.error("Error inesperado al enviar notificación: %s", exc)
        return False


# ── Formateador de comentarios ───────────────────────────────


def _format_review_comment(result: ReviewResult) -> str:
    """Formatea el resultado de la revisión como comentario Markdown."""
    if result.passed:
        return (
            "## :white_check_mark: Revisión Automática — APROBADO\n\n"
            "Todas las reglas de validación pasaron correctamente.\n\n"
            "**LGTM** — Listo para merge.\n\n"
            "---\n"
            "_Revisión automática por SOMER_"
        )

    # Separar por severidad
    critical = [v for v in result.violations if v.severity == "critical"]
    warnings = [v for v in result.violations if v.severity == "warning"]
    info = [v for v in result.violations if v.severity == "info"]

    lines: List[str] = []

    if critical:
        lines.append("## :x: Revisión Automática — RECHAZADO\n")
        lines.append(
            "Se encontraron violaciones **críticas** que impiden la aprobación.\n"
        )
    else:
        lines.append("## :warning: Revisión Automática — ADVERTENCIAS\n")
        lines.append(
            "El PR tiene advertencias que deben revisarse, pero no se rechazó.\n"
        )

    if critical:
        lines.append("### Errores Críticos\n")
        for v in critical:
            lines.append(f"- :red_circle: **{v.rule}**: {v.message}")
        lines.append("")

    if warnings:
        lines.append("### Advertencias\n")
        for v in warnings:
            lines.append(f"- :large_orange_diamond: **{v.rule}**: {v.message}")
        lines.append("")

    if info:
        lines.append("### Información\n")
        for v in info:
            lines.append(f"- :information_source: **{v.rule}**: {v.message}")
        lines.append("")

    lines.append("---")
    lines.append("_Revisión automática por SOMER_")

    return "\n".join(lines)


def _format_whatsapp_notification(result: ReviewResult) -> str:
    """Formatea el mensaje de notificación para WhatsApp."""
    repo_full = f"{result.workspace}/{result.repo}"
    header = f"*SOMER PR Review* - {repo_full}\n"
    header += f"PR #{result.pr_id}: {result.pr_title}\n\n"

    if result.has_critical:
        header += f"Estado: RECHAZADO\n"
        header += f"Accion: {result.action}\n\n"
    else:
        header += f"Estado: ADVERTENCIAS\n"
        header += f"Accion: {result.action}\n\n"

    violations_text: List[str] = []
    for v in result.violations:
        icon = "X" if v.severity == "critical" else "!"
        violations_text.append(f"[{icon}] {v.rule}: {v.message}")

    body = "\n".join(violations_text[:10])  # Limitar a 10 para WhatsApp
    if len(result.violations) > 10:
        body += f"\n... y {len(result.violations) - 10} mas."

    return header + body


# ── Revisor principal ────────────────────────────────────────


class PRReviewer:
    """Revisor automático de Pull Requests de Bitbucket.

    Conecta con la API, evalúa reglas, publica comentarios,
    aprueba/rechaza y notifica por WhatsApp.
    """

    def __init__(
        self,
        rules_path: Optional[str] = None,
        credentials_key: Optional[str] = None,
    ) -> None:
        self.client = BitbucketClient(credentials_key=credentials_key)
        self.engine = RulesEngine(rules_path)
        self._credentials_key = credentials_key

    async def close(self) -> None:
        """Cierra la sesión HTTP."""
        await self.client.close()

    async def list_prs(
        self, workspace: str, repo: str, state: str = "OPEN"
    ) -> List[Dict[str, Any]]:
        """Lista PRs de un repositorio."""
        prs = await self.client.list_prs(workspace, repo, state)
        return [
            {
                "id": pr["id"],
                "title": pr["title"],
                "state": pr["state"],
                "author": pr.get("author", {}).get("display_name", "desconocido"),
                "source": pr.get("source", {}).get("branch", {}).get("name", ""),
                "destination": pr.get("destination", {}).get("branch", {}).get("name", ""),
                "created_on": pr.get("created_on", ""),
                "comment_count": pr.get("comment_count", 0),
            }
            for pr in prs
        ]

    async def get_pr_diff(
        self, workspace: str, repo: str, pr_id: int
    ) -> str:
        """Obtiene el diff de un PR."""
        return await self.client.get_pr_diff(workspace, repo, pr_id)

    async def review_pr(
        self,
        workspace: str,
        repo: str,
        pr_id: int,
        *,
        auto_action: bool = True,
        notify_phone: Optional[str] = None,
    ) -> ReviewResult:
        """Revisa un PR contra las reglas configuradas.

        Args:
            workspace: Workspace de Bitbucket.
            repo: Slug del repositorio.
            pr_id: ID del Pull Request.
            auto_action: Si True, aprueba/rechaza automáticamente.
            notify_phone: Número para notificación WhatsApp (None = no notificar).

        Returns:
            ReviewResult con los detalles de la revisión.
        """
        try:
            # Obtener datos del PR
            logger.info("Revisando PR #%d en %s/%s...", pr_id, workspace, repo)
            pr_data = await self.client.get_pr(workspace, repo, pr_id)
            diff = await self.client.get_pr_diff(workspace, repo, pr_id)
            commits = await self.client.get_pr_commits(workspace, repo, pr_id)

            result = ReviewResult(
                pr_id=pr_id,
                pr_title=pr_data.get("title", "Sin título"),
                repo=repo,
                workspace=workspace,
            )

            # Evaluar reglas
            result.violations = self.engine.evaluate(pr_data, diff, commits)

            # Publicar comentario
            comment = _format_review_comment(result)
            try:
                await self.client.post_comment(workspace, repo, pr_id, comment)
                result.comment_posted = True
                logger.info("Comentario publicado en PR #%d", pr_id)
            except Exception as exc:
                logger.error("Error al publicar comentario: %s", exc)

            # Acción automática
            if auto_action:
                if result.passed:
                    try:
                        await self.client.approve_pr(workspace, repo, pr_id)
                        result.action = "approved"
                        logger.info("PR #%d aprobado", pr_id)
                    except Exception as exc:
                        logger.error("Error al aprobar PR #%d: %s", pr_id, exc)
                        result.action = "error_approving"
                elif result.has_critical:
                    try:
                        await self.client.decline_pr(workspace, repo, pr_id)
                        result.action = "declined"
                        logger.info("PR #%d rechazado", pr_id)
                    except Exception as exc:
                        logger.error("Error al rechazar PR #%d: %s", pr_id, exc)
                        result.action = "error_declining"
                else:
                    result.action = "commented"
            else:
                result.action = "reviewed_only"

            # Notificación WhatsApp
            if notify_phone and not result.passed:
                wa_message = _format_whatsapp_notification(result)
                sent = _send_whatsapp_notification(notify_phone, wa_message)
                result.notification_sent = sent

            return result

        except Exception as exc:
            logger.error("Error al revisar PR #%d: %s", pr_id, exc)
            return ReviewResult(
                pr_id=pr_id,
                pr_title="",
                repo=repo,
                workspace=workspace,
                error=str(exc),
            )

    async def review_all_prs(
        self,
        workspace: str,
        repo: str,
        *,
        auto_action: bool = True,
        notify_phone: Optional[str] = None,
    ) -> List[ReviewResult]:
        """Revisa todos los PRs abiertos de un repositorio.

        Returns:
            Lista de ReviewResult, uno por cada PR.
        """
        prs = await self.client.list_prs(workspace, repo, "OPEN")
        results: List[ReviewResult] = []
        for pr in prs:
            pr_id = pr["id"]
            result = await self.review_pr(
                workspace, repo, pr_id,
                auto_action=auto_action,
                notify_phone=notify_phone,
            )
            results.append(result)
        return results

    @staticmethod
    async def review_all_repos(
        *,
        rules_path: Optional[str] = None,
        auto_action: bool = True,
    ) -> List[Dict[str, Any]]:
        """Revisa todos los PRs abiertos de TODOS los repos activos configurados.

        Lee repos_config.json, itera sobre los repositorios activos,
        crea un PRReviewer con las credenciales adecuadas para cada uno
        y revisa todos los PRs abiertos.

        Returns:
            Lista de dicts, uno por repo, con los resultados de revision.
        """
        config = _load_repos_config()
        if not config:
            return [{"success": False, "error": "No se encontro repos_config.json o esta vacio."}]

        repos = config.get("repositories", [])
        active_repos = [r for r in repos if r.get("active", True)]
        if not active_repos:
            return [{"success": False, "error": "No hay repositorios activos configurados."}]

        all_results: List[Dict[str, Any]] = []

        for repo_cfg in active_repos:
            workspace = repo_cfg.get("workspace", config.get("default_workspace", ""))
            repo_slug = repo_cfg.get("repo_slug", "")
            creds_key = repo_cfg.get("credentials_key", config.get("default_credentials"))
            notify_phones = repo_cfg.get("notify_phones", [])
            notify_phone = notify_phones[0] if notify_phones else None

            if not workspace or not repo_slug:
                all_results.append({
                    "success": False,
                    "repo": repo_slug or "desconocido",
                    "workspace": workspace or "desconocido",
                    "error": "Faltan workspace o repo_slug en la configuracion.",
                })
                continue

            reviewer = PRReviewer(
                rules_path=rules_path,
                credentials_key=creds_key,
            )
            try:
                results = await reviewer.review_all_prs(
                    workspace, repo_slug,
                    auto_action=auto_action,
                    notify_phone=notify_phone if auto_action else None,
                )
                summaries = [r.to_dict() for r in results]
                approved = sum(1 for r in results if r.passed)
                declined = sum(1 for r in results if r.has_critical)
                warned = sum(1 for r in results if r.has_warnings and not r.has_critical)

                all_results.append({
                    "success": True,
                    "workspace": workspace,
                    "repo": repo_slug,
                    "label": repo_cfg.get("label", repo_slug),
                    "total_reviewed": len(results),
                    "approved": approved,
                    "declined": declined,
                    "warnings": warned,
                    "results": summaries,
                })
            except Exception as exc:
                logger.error("Error al revisar repo %s/%s: %s", workspace, repo_slug, exc)
                all_results.append({
                    "success": False,
                    "workspace": workspace,
                    "repo": repo_slug,
                    "error": str(exc),
                })
            finally:
                await reviewer.close()

        return all_results


# ── CLI ──────────────────────────────────────────────────────


def _setup_logging(verbose: bool = False) -> None:
    """Configura logging a stderr."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


async def _cli_list(args: List[str]) -> int:
    """Subcomando: list <workspace> <repo> [--state STATE]"""
    if len(args) < 2:
        print("Uso: pr_reviewer.py list <workspace> <repo> [--state OPEN]", file=sys.stderr)
        return 1

    workspace, repo = args[0], args[1]
    state = "OPEN"
    if "--state" in args:
        idx = args.index("--state")
        if idx + 1 < len(args):
            state = args[idx + 1]

    reviewer = PRReviewer()
    try:
        prs = await reviewer.list_prs(workspace, repo, state)
        if not prs:
            print(f"No se encontraron PRs con estado '{state}' en {workspace}/{repo}")
            return 0
        print(f"\nPRs ({state}) en {workspace}/{repo}:")
        print("-" * 70)
        for pr in prs:
            print(
                f"  #{pr['id']:4d}  {pr['title'][:50]:<50}  "
                f"{pr['source']} -> {pr['destination']}"
            )
        print(f"\nTotal: {len(prs)} PRs")
        return 0
    finally:
        await reviewer.close()


async def _cli_review(args: List[str]) -> int:
    """Subcomando: review <workspace> <repo> <pr_id> [flags]"""
    if len(args) < 3:
        print(
            "Uso: pr_reviewer.py review <workspace> <repo> <pr_id> "
            "[--rules path] [--auto] [--notify phone]",
            file=sys.stderr,
        )
        return 1

    workspace, repo = args[0], args[1]
    try:
        pr_id = int(args[2])
    except ValueError:
        print(f"PR ID inválido: {args[2]}", file=sys.stderr)
        return 1

    rules_path = None
    auto_action = "--auto" in args
    notify_phone = None

    if "--rules" in args:
        idx = args.index("--rules")
        if idx + 1 < len(args):
            rules_path = args[idx + 1]

    if "--notify" in args:
        idx = args.index("--notify")
        if idx + 1 < len(args):
            notify_phone = args[idx + 1]

    reviewer = PRReviewer(rules_path=rules_path)
    try:
        result = await reviewer.review_pr(
            workspace, repo, pr_id,
            auto_action=auto_action,
            notify_phone=notify_phone,
        )
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 0 if not result.error else 1
    finally:
        await reviewer.close()


async def _cli_review_all(args: List[str]) -> int:
    """Subcomando: review-all <workspace> <repo> [flags]"""
    if len(args) < 2:
        print(
            "Uso: pr_reviewer.py review-all <workspace> <repo> "
            "[--rules path] [--auto] [--notify phone]",
            file=sys.stderr,
        )
        return 1

    workspace, repo = args[0], args[1]
    rules_path = None
    auto_action = "--auto" in args
    notify_phone = None

    if "--rules" in args:
        idx = args.index("--rules")
        if idx + 1 < len(args):
            rules_path = args[idx + 1]

    if "--notify" in args:
        idx = args.index("--notify")
        if idx + 1 < len(args):
            notify_phone = args[idx + 1]

    reviewer = PRReviewer(rules_path=rules_path)
    try:
        results = await reviewer.review_all_prs(
            workspace, repo,
            auto_action=auto_action,
            notify_phone=notify_phone,
        )
        output = [r.to_dict() for r in results]
        print(json.dumps(output, indent=2, ensure_ascii=False))
        has_errors = any(r.error for r in results)
        return 1 if has_errors else 0
    finally:
        await reviewer.close()


async def _cli_main() -> int:
    """Punto de entrada CLI."""
    args = sys.argv[1:]
    verbose = "--verbose" in args or "-v" in args
    args = [a for a in args if a not in ("--verbose", "-v")]

    _setup_logging(verbose)

    if not args:
        print(
            "Uso: pr_reviewer.py <command> [args]\n\n"
            "Comandos:\n"
            "  list        Listar PRs de un repositorio\n"
            "  review      Revisar un PR específico\n"
            "  review-all  Revisar todos los PRs abiertos\n",
            file=sys.stderr,
        )
        return 1

    command = args[0]
    sub_args = args[1:]

    if command == "list":
        return await _cli_list(sub_args)
    elif command == "review":
        return await _cli_review(sub_args)
    elif command == "review-all":
        return await _cli_review_all(sub_args)
    else:
        print(f"Comando desconocido: {command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_cli_main()))
