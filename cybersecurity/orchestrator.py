"""Orquestador de pentesting — coordina las fases de un engagement.

El orquestador NO ejecuta scanners ni exploits directamente.
Delega a los módulos especializados y consolida resultados.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from cybersecurity.types import (
    Finding,
    PentestPhase,
    PentestPlan,
    PhaseResult,
    Severity,
)
from cybersecurity.workspace import SecurityWorkspace

logger = logging.getLogger(__name__)


class PentestOrchestrator:
    """Orquesta las fases de un engagement de pentesting."""

    def __init__(self, workspace: Optional[SecurityWorkspace] = None) -> None:
        self._ws = workspace or SecurityWorkspace()

    def plan_engagement(self, target_url: str, scope: str = "full") -> PentestPlan:
        """Genera un plan de engagement de pentesting.

        Args:
            target_url: URL del target.
            scope: Alcance ('full', 'quick', 'recon-only').

        Returns:
            PentestPlan con fases y workspace configurados.
        """
        from cybersecurity.utils import normalize_url, extract_hostname

        target_url = normalize_url(target_url)
        hostname = extract_hostname(target_url)

        phases = [PentestPhase.RECON, PentestPhase.SCAN, PentestPhase.EXPLOIT,
                  PentestPhase.EVIDENCE, PentestPhase.REPORT]
        if scope == "quick":
            phases = [PentestPhase.RECON, PentestPhase.SCAN, PentestPhase.REPORT]
        elif scope == "recon-only":
            phases = [PentestPhase.RECON, PentestPhase.REPORT]

        ws_path = self._ws.create_scan_workspace(target_url)

        plan = PentestPlan(
            target_url=target_url,
            hostname=hostname,
            scope=scope,
            phases=phases,
            workspace_path=str(ws_path),
        )

        self._ws.save_plan(ws_path, plan)
        logger.info("Plan de pentesting creado: %s (scope=%s)", target_url, scope)
        return plan

    async def run_recon(self, plan: PentestPlan) -> PhaseResult:
        """Ejecuta fase de reconocimiento.

        Incluye: discover_tech, dns_lookup, scan_ports, enumerate_subdomains, detect_waf.
        """
        start = time.monotonic()
        result = PhaseResult(phase=PentestPhase.RECON)
        data: Dict[str, Any] = {}
        ws_path = Path(plan.workspace_path) if plan.workspace_path else None

        try:
            from cybersecurity.scanners import discover_tech, dns_lookup, scan_ports
            from cybersecurity.scanners_advanced import detect_waf, enumerate_subdomains

            # Discover tech
            tech = await discover_tech(plan.target_url)
            data["tech"] = tech.model_dump()
            if ws_path:
                self._ws.save_recon_data(ws_path, "tech.json", tech)

            # DNS lookup
            dns = await dns_lookup(plan.hostname)
            data["dns"] = dns.model_dump()
            if ws_path:
                self._ws.save_recon_data(ws_path, "dns.json", dns)

            # Port scan
            ports = await scan_ports(plan.hostname)
            data["ports"] = ports.model_dump()
            if ws_path:
                self._ws.save_recon_data(ws_path, "ports.json", ports)

            # Subdomain enumeration
            subdomains, sub_findings = await enumerate_subdomains(plan.hostname)
            data["subdomains"] = [s.model_dump() for s in subdomains]
            if ws_path:
                self._ws.save_recon_data(ws_path, "subdomains.json",
                                         [s.model_dump() for s in subdomains])

            # WAF detection
            waf = await detect_waf(plan.target_url)
            data["waf"] = waf.model_dump()
            if ws_path:
                self._ws.save_recon_data(ws_path, "waf.json", waf)

            # Contar findings
            all_findings: List[Finding] = []
            for section in [tech, dns, ports]:
                if hasattr(section, "findings"):
                    all_findings.extend(section.findings)
            all_findings.extend(sub_findings)
            all_findings.extend(waf.findings)

            result.findings_count = len(all_findings)
            data["all_findings"] = [f.model_dump() for f in all_findings]
            result.success = True

        except Exception as exc:
            logger.error("Error en fase de recon: %s", exc)
            result.error = str(exc)[:500]

        result.data = data
        result.duration_secs = round(time.monotonic() - start, 2)
        return result

    async def run_scan(
        self, plan: PentestPlan, recon_data: Optional[Dict[str, Any]] = None
    ) -> PhaseResult:
        """Ejecuta fase de escaneo de vulnerabilidades.

        Incluye: security_scan (18 checks) + 10 scanners avanzados.
        """
        start = time.monotonic()
        result = PhaseResult(phase=PentestPhase.SCAN)
        data: Dict[str, Any] = {}
        ws_path = Path(plan.workspace_path) if plan.workspace_path else None

        try:
            from cybersecurity.scanners import (
                analyze_csp, check_cookies, check_cors, check_directory_listing,
                check_email_security, check_forms, check_headers, check_html_leaks,
                check_http_methods, check_https_redirect, check_mixed_content,
                check_sri, check_ssl, check_xss_reflection, discover_paths,
                discover_tech, dns_lookup, scan_ports,
            )
            from cybersecurity.scanners_advanced import (
                analyze_jwt, check_admin_panels, check_info_disclosure,
                check_path_traversal, check_request_smuggling,
                check_session_management, check_sqli_indicators, check_ssti,
            )
            from cybersecurity.report import calculate_risk_score
            from cybersecurity.types import ScanReport

            url = plan.target_url
            hostname = plan.hostname

            # Escaneo base (18 checks)
            report = ScanReport(target_url=url)
            report.headers = await check_headers(url)
            report.ssl = await check_ssl(hostname)
            report.cookies = await check_cookies(url)
            report.tech = await discover_tech(url)
            report.dns = await dns_lookup(hostname)
            report.paths = await discover_paths(url)
            report.cors = await check_cors(url)
            report.forms = await check_forms(url)
            report.xss = await check_xss_reflection(url)
            report.ports = await scan_ports(hostname)
            report.http_methods = await check_http_methods(url)
            report.https_redirect = await check_https_redirect(url)
            report.sri = await check_sri(url)
            report.mixed_content = await check_mixed_content(url)
            report.directory_listing = await check_directory_listing(url)
            report.html_leaks = await check_html_leaks(url)
            report.csp = await analyze_csp(url)
            report.email_security = await check_email_security(hostname)

            report.collect_findings()
            report.risk_score = calculate_risk_score(report.all_findings)

            # Scanners avanzados
            advanced_findings: List[Finding] = []
            advanced_findings.extend(await check_sqli_indicators(url))
            advanced_findings.extend(await check_admin_panels(url))
            advanced_findings.extend(await check_session_management(url))
            advanced_findings.extend(await check_request_smuggling(url))
            advanced_findings.extend(await check_ssti(url))
            advanced_findings.extend(await check_path_traversal(url))
            advanced_findings.extend(await check_info_disclosure(url))
            jwt_result = await analyze_jwt(url)
            advanced_findings.extend(jwt_result.findings)

            # Combinar findings
            all_findings = report.all_findings + advanced_findings
            report.all_findings = all_findings
            report.risk_score = calculate_risk_score(all_findings)

            data["scan_report"] = report.model_dump()
            data["advanced_findings"] = [f.model_dump() for f in advanced_findings]
            result.findings_count = len(all_findings)

            # Guardar
            if ws_path:
                self._ws.save_scan_report(ws_path, report)
                from cybersecurity.report import generate_markdown_report
                md = generate_markdown_report(report)
                self._ws.save_scan_report_md(ws_path, md)

            result.success = True

        except Exception as exc:
            logger.error("Error en fase de scan: %s", exc)
            result.error = str(exc)[:500]

        result.data = data
        result.duration_secs = round(time.monotonic() - start, 2)
        return result

    async def run_exploits(
        self, plan: PentestPlan, scan_data: Optional[Dict[str, Any]] = None
    ) -> PhaseResult:
        """Ejecuta fase de explotación.

        Incluye: exploits originales (14) + exploits avanzados (10).
        """
        start = time.monotonic()
        result = PhaseResult(phase=PentestPhase.EXPLOIT)
        data: Dict[str, Any] = {}
        ws_path = Path(plan.workspace_path) if plan.workspace_path else None

        try:
            from cybersecurity.exploits import run_exploits
            from cybersecurity.types import ScanReport

            # Reconstruir findings del scan
            findings: List[Finding] = []
            if scan_data and "scan_report" in scan_data:
                report = ScanReport.model_validate(scan_data["scan_report"])
                report.collect_findings()
                findings = report.all_findings
            elif scan_data and "all_findings" in scan_data:
                findings = [Finding.model_validate(f) for f in scan_data["all_findings"]]

            if not findings:
                result.error = "No hay findings para explotar"
                result.data = data
                result.duration_secs = round(time.monotonic() - start, 2)
                return result

            # Ejecutar exploits (incluye originales + avanzados via _EXPLOIT_MAP)
            exploit_report = await run_exploits(
                url=plan.target_url,
                findings=findings,
                workspace_dir=ws_path or Path("/tmp"),
                use_browser=True,
            )

            data["exploit_report"] = exploit_report.model_dump()
            data["total_exploits"] = exploit_report.total_exploits
            data["successful"] = exploit_report.successful
            data["failed"] = exploit_report.failed
            result.findings_count = exploit_report.successful

            if ws_path:
                self._ws.save_exploit_report(ws_path, exploit_report)

            result.success = True

        except Exception as exc:
            logger.error("Error en fase de exploit: %s", exc)
            result.error = str(exc)[:500]

        result.data = data
        result.duration_secs = round(time.monotonic() - start, 2)
        return result

    async def run_evidence(
        self, plan: PentestPlan, exploit_data: Optional[Dict[str, Any]] = None
    ) -> PhaseResult:
        """Ejecuta fase de evidencia — screenshots, cadena, export.

        Args:
            plan: Plan del engagement.
            exploit_data: Datos de la fase de explotación.
        """
        start = time.monotonic()
        result = PhaseResult(phase=PentestPhase.EVIDENCE)
        data: Dict[str, Any] = {}
        ws_path = Path(plan.workspace_path) if plan.workspace_path else None

        try:
            from cybersecurity.evidence import EvidenceManager
            from cybersecurity.types import ExploitResult as ER

            if not ws_path:
                result.error = "No hay workspace configurado"
                result.duration_secs = round(time.monotonic() - start, 2)
                return result

            em = EvidenceManager(ws_path)

            # Construir cadena de evidencia
            findings: List[Finding] = []
            exploit_results: List[ER] = []

            if exploit_data:
                if "exploit_report" in exploit_data:
                    report_data = exploit_data["exploit_report"]
                    if "results" in report_data:
                        exploit_results = [
                            ER.model_validate(r) for r in report_data["results"]
                        ]

            chain = em.build_chain(findings, exploit_results, plan.target_url)
            data["evidence_chain"] = chain.model_dump()

            # Export package
            zip_path = em.export_package()
            if zip_path:
                data["package_path"] = zip_path

            result.success = True

        except Exception as exc:
            logger.error("Error en fase de evidencia: %s", exc)
            result.error = str(exc)[:500]

        result.data = data
        result.duration_secs = round(time.monotonic() - start, 2)
        return result

    def generate_final_report(self, plan: PentestPlan) -> str:
        """Genera reporte Markdown final consolidado.

        Args:
            plan: Plan del engagement con resultados de fases.

        Returns:
            Contenido Markdown del reporte final.
        """
        ws_path = Path(plan.workspace_path) if plan.workspace_path else None
        lines = [
            f"# Reporte de Pentesting — {plan.target_url}",
            "",
            f"**Scope:** {plan.scope} | **Hostname:** {plan.hostname}",
            f"**Creado:** {plan.created_at}",
            "",
            "---",
            "",
        ]

        # Resumen de fases
        lines.append("## Resumen de Fases")
        lines.append("")
        lines.append("| Fase | Estado | Duración | Findings |")
        lines.append("|------|--------|----------|----------|")

        for phase in plan.phases:
            pr = plan.phase_results.get(phase.value)
            if pr:
                status = "OK" if pr.success else "ERROR"
                lines.append(
                    f"| {phase.value.upper()} | {status} | "
                    f"{pr.duration_secs}s | {pr.findings_count} |"
                )
            else:
                lines.append(f"| {phase.value.upper()} | Pendiente | - | - |")

        lines.append("")

        # Detalle de cada fase
        for phase in plan.phases:
            pr = plan.phase_results.get(phase.value)
            if not pr:
                continue

            lines.append(f"## Fase: {phase.value.upper()}")
            lines.append("")

            if pr.error:
                lines.append(f"**Error:** {pr.error}")
                lines.append("")
                continue

            if phase == PentestPhase.RECON:
                self._render_recon_section(lines, pr)
            elif phase == PentestPhase.SCAN:
                self._render_scan_section(lines, pr)
            elif phase == PentestPhase.EXPLOIT:
                self._render_exploit_section(lines, pr)
            elif phase == PentestPhase.EVIDENCE:
                self._render_evidence_section(lines, pr)

            lines.append("---")
            lines.append("")

        # Guardar
        md_content = "\n".join(lines)
        if ws_path:
            md_path = ws_path / "final_report.md"
            try:
                md_path.write_text(md_content, encoding="utf-8")
            except Exception:
                pass

        return md_content

    @staticmethod
    def _render_recon_section(lines: List[str], pr: PhaseResult) -> None:
        data = pr.data
        if "tech" in data:
            techs = data["tech"].get("technologies", [])
            if techs:
                lines.append("### Tecnologías Detectadas")
                for t in techs[:10]:
                    lines.append(f"- {t.get('name', 'N/A')}: {t.get('version', 'N/A')}")
                lines.append("")

        if "subdomains" in data:
            subs = data["subdomains"]
            if subs:
                lines.append(f"### Subdominios ({len(subs)} encontrados)")
                for s in subs[:15]:
                    sub = s if isinstance(s, str) else s.get("subdomain", "N/A")
                    lines.append(f"- {sub}")
                lines.append("")

        if "waf" in data:
            waf = data["waf"]
            if waf.get("detected"):
                lines.append(f"### WAF Detectado: {waf.get('waf_name', 'N/A')}")
                lines.append(f"Confianza: {waf.get('confidence', 'N/A')}")
                lines.append("")

    @staticmethod
    def _render_scan_section(lines: List[str], pr: PhaseResult) -> None:
        data = pr.data
        if "scan_report" in data:
            report = data["scan_report"]
            risk = report.get("risk_score", 0)
            findings = report.get("all_findings", [])
            lines.append(f"**Riesgo:** {risk}/10 | **Findings:** {len(findings)}")
            lines.append("")

            # Top findings por severidad
            by_sev: Dict[str, int] = {}
            for f in findings:
                sev = f.get("severity", "info")
                by_sev[sev] = by_sev.get(sev, 0) + 1
            for sev in ["critical", "high", "medium", "low", "info"]:
                if sev in by_sev:
                    lines.append(f"- **{sev.upper()}:** {by_sev[sev]}")
            lines.append("")

    @staticmethod
    def _render_exploit_section(lines: List[str], pr: PhaseResult) -> None:
        data = pr.data
        lines.append(
            f"**Total:** {data.get('total_exploits', 0)} | "
            f"**Exitosos:** {data.get('successful', 0)} | "
            f"**Fallidos:** {data.get('failed', 0)}"
        )
        lines.append("")

        if "exploit_report" in data:
            results = data["exploit_report"].get("results", [])
            for r in results:
                if r.get("success"):
                    lines.append(f"- **{r.get('title', 'N/A')}** — {r.get('impact_description', '')[:100]}")
            lines.append("")

    @staticmethod
    def _render_evidence_section(lines: List[str], pr: PhaseResult) -> None:
        data = pr.data
        if "package_path" in data:
            lines.append(f"**Paquete de evidencia:** `{data['package_path']}`")
            lines.append("")
        if "evidence_chain" in data:
            chain = data["evidence_chain"]
            links = chain.get("links", [])
            lines.append(f"**Cadena de evidencia:** {len(links)} eslabones")
            lines.append("")
