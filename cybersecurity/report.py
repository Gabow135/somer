"""Generación de reportes de seguridad en Markdown."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from cybersecurity.remediation import (
    format_remediation_markdown,
    get_remediations_for_findings,
)
from cybersecurity.types import Finding, RemediationGuide, ScanReport, Severity


# ── Pesos por severidad para risk score ──────────────────────

_SEVERITY_WEIGHTS: Dict[Severity, float] = {
    Severity.CRITICAL: 3.0,
    Severity.HIGH: 2.0,
    Severity.MEDIUM: 1.0,
    Severity.LOW: 0.3,
    Severity.INFO: 0.0,
}

_SEVERITY_LABELS: Dict[Severity, str] = {
    Severity.CRITICAL: "CRÍTICO",
    Severity.HIGH: "ALTO",
    Severity.MEDIUM: "MEDIO",
    Severity.LOW: "BAJO",
    Severity.INFO: "INFO",
}


def calculate_risk_score(findings: List[Finding]) -> float:
    """Calcula puntuación de riesgo 0.0-10.0 basada en severidades."""
    if not findings:
        return 0.0

    total_weight = sum(_SEVERITY_WEIGHTS.get(f.severity, 0.0) for f in findings)
    # Escalar: 10 puntos = score 10 (máximo)
    score = min(10.0, total_weight)
    return round(score, 1)


def findings_to_summary(findings: List[Finding]) -> str:
    """Genera un resumen conciso de findings para respuesta en chat."""
    if not findings:
        return "No se encontraron hallazgos de seguridad."

    counts: Dict[str, int] = {}
    for f in findings:
        label = _SEVERITY_LABELS.get(f.severity, f.severity.value)
        counts[label] = counts.get(label, 0) + 1

    parts = []
    for label in ["CRÍTICO", "ALTO", "MEDIO", "BAJO", "INFO"]:
        if label in counts:
            parts.append(f"{counts[label]} {label}")

    summary = f"**{len(findings)} hallazgos:** {', '.join(parts)}"

    # Top findings
    critical_high = [
        f for f in findings
        if f.severity in (Severity.CRITICAL, Severity.HIGH)
    ]
    if critical_high:
        summary += "\n\n**Hallazgos más importantes:**"
        for f in critical_high[:5]:
            label = _SEVERITY_LABELS.get(f.severity, "")
            summary += f"\n- [{label}] {f.title}"

    return summary


def _render_remediation_section(guides: List[RemediationGuide]) -> str:
    """Genera sección de remediaciones con bloques colapsables."""
    if not guides:
        return ""

    lines: List[str] = []
    lines.append("## Remediaciones Detalladas")
    lines.append("")
    for guide in guides:
        lines.append(format_remediation_markdown(guide))
    return "\n".join(lines)


def generate_markdown_report(report: ScanReport) -> str:
    """Genera reporte Markdown completo."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    risk_emoji = _risk_emoji(report.risk_score)

    lines: List[str] = []
    lines.append("# Reporte de Seguridad Web")
    lines.append("")
    lines.append(f"**Objetivo:** `{report.target_url}`")
    lines.append(f"**Fecha:** {now}")
    lines.append(f"**Duración del escaneo:** {report.scan_duration_secs:.1f}s")
    lines.append(f"**Puntuación de riesgo:** {risk_emoji} **{report.risk_score}/10**")
    lines.append("")

    # ── Resumen por severidad ────────────────────────────────
    lines.append("## Resumen")
    lines.append("")
    counts: Dict[str, int] = {}
    for f in report.all_findings:
        label = _SEVERITY_LABELS.get(f.severity, f.severity.value)
        counts[label] = counts.get(label, 0) + 1

    lines.append("| Severidad | Cantidad |")
    lines.append("|-----------|----------|")
    for label in ["CRÍTICO", "ALTO", "MEDIO", "BAJO", "INFO"]:
        count = counts.get(label, 0)
        if count > 0:
            lines.append(f"| {label} | {count} |")
    lines.append(f"| **Total** | **{len(report.all_findings)}** |")
    lines.append("")

    # ── Hallazgos por severidad ──────────────────────────────
    for severity in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]:
        section_findings = [f for f in report.all_findings if f.severity == severity]
        if not section_findings:
            continue

        label = _SEVERITY_LABELS[severity]
        lines.append(f"## Hallazgos {label}")
        lines.append("")

        for i, f in enumerate(section_findings, 1):
            lines.append(f"### {i}. {f.title}")
            lines.append("")
            if f.cwe:
                lines.append(f"**CWE:** {f.cwe}")
            lines.append(f"**Detalle:** {f.detail}")
            if f.evidence:
                lines.append(f"**Evidencia:** `{f.evidence}`")
            lines.append(f"**Remediación:** {f.remediation}")
            lines.append("")

    # ── Headers de seguridad ─────────────────────────────────
    if report.headers:
        lines.append("## Headers de Seguridad")
        lines.append("")
        lines.append("| Header | Estado |")
        lines.append("|--------|--------|")
        for name, val in report.headers.present.items():
            display_val = val[:60] + "..." if len(val) > 60 else val
            lines.append(f"| {name} | Presente: `{display_val}` |")
        for name in report.headers.missing:
            lines.append(f"| {name} | **Ausente** |")
        lines.append("")

    # ── SSL/TLS ──────────────────────────────────────────────
    if report.ssl:
        lines.append("## Certificado SSL/TLS")
        lines.append("")
        lines.append(f"- **Válido:** {'Sí' if report.ssl.valid else 'No'}")
        if report.ssl.issuer:
            lines.append(f"- **Emisor:** {report.ssl.issuer}")
        if report.ssl.expires:
            lines.append(f"- **Expira:** {report.ssl.expires}")
        if report.ssl.protocol:
            lines.append(f"- **Protocolo:** {report.ssl.protocol}")
        if report.ssl.cipher:
            lines.append(f"- **Cipher:** {report.ssl.cipher}")
        lines.append("")

    # ── Tecnologías ──────────────────────────────────────────
    if report.tech and report.tech.technologies:
        lines.append("## Tecnologías Detectadas")
        lines.append("")
        lines.append("| Tecnología | Detectado en |")
        lines.append("|------------|-------------|")
        for tech in report.tech.technologies:
            lines.append(f"| {tech['name']} | {tech.get('detected_in', '')} |")
        lines.append("")

    # ── Cookies ──────────────────────────────────────────────
    if report.cookies and report.cookies.cookies:
        lines.append("## Cookies")
        lines.append("")
        lines.append("| Cookie | Secure | HttpOnly | SameSite |")
        lines.append("|--------|--------|----------|----------|")
        for c in report.cookies.cookies:
            lines.append(
                f"| {c.name} | "
                f"{'Sí' if c.secure else '**No**'} | "
                f"{'Sí' if c.httponly else '**No**'} | "
                f"{c.samesite or '**No**'} |"
            )
        lines.append("")

    # ── Rutas descubiertas ───────────────────────────────────
    if report.paths and report.paths.found:
        lines.append("## Rutas Descubiertas")
        lines.append("")
        lines.append("| Ruta | Código HTTP | Tamaño |")
        lines.append("|------|------------|--------|")
        for p in report.paths.found:
            lines.append(f"| `{p.path}` | {p.status_code} | {p.content_length} bytes |")
        lines.append("")

    # ── Puertos ──────────────────────────────────────────────
    if report.ports and report.ports.open_ports:
        lines.append("## Puertos Abiertos")
        lines.append("")
        lines.append("| Puerto | Servicio |")
        lines.append("|--------|----------|")
        for p in report.ports.open_ports:
            lines.append(f"| {p.port} | {p.service} |")
        lines.append("")

    # ── DNS ───────────────────────────────────────────────────
    if report.dns and report.dns.records:
        lines.append("## Registros DNS")
        lines.append("")
        for rtype, records in report.dns.records.items():
            lines.append(f"**{rtype}:** {', '.join(records[:5])}")
        lines.append("")

    # ── CSP (análisis detallado) ─────────────────────────────
    if report.csp and report.csp.raw_policy:
        lines.append("## Análisis CSP Detallado")
        lines.append("")
        lines.append(f"**Política:** `{report.csp.raw_policy[:200]}`")
        lines.append(f"- **unsafe-inline:** {'Sí' if report.csp.has_unsafe_inline else 'No'}")
        lines.append(f"- **unsafe-eval:** {'Sí' if report.csp.has_unsafe_eval else 'No'}")
        if report.csp.directives:
            lines.append(f"- **Directivas:** {', '.join(report.csp.directives.keys())}")
        lines.append("")

    # ── Métodos HTTP ─────────────────────────────────────────
    if report.http_methods and report.http_methods.allowed_methods:
        lines.append("## Métodos HTTP")
        lines.append("")
        lines.append(f"- **Permitidos:** {', '.join(report.http_methods.allowed_methods)}")
        if report.http_methods.unsafe_methods:
            lines.append(f"- **Inseguros:** {', '.join(report.http_methods.unsafe_methods)}")
        lines.append("")

    # ── HTTPS Redirect ───────────────────────────────────────
    if report.https_redirect:
        lines.append("## Redirección HTTPS")
        lines.append("")
        status = "Sí" if report.https_redirect.redirects_to_https else "**No**"
        lines.append(f"- **Redirige a HTTPS:** {status}")
        if report.https_redirect.redirect_chain:
            lines.append(f"- **Cadena:** {' → '.join(report.https_redirect.redirect_chain[:5])}")
        lines.append("")

    # ── SRI ──────────────────────────────────────────────────
    if report.sri and report.sri.external_scripts > 0:
        lines.append("## Subresource Integrity (SRI)")
        lines.append("")
        lines.append(f"- **Recursos externos:** {report.sri.external_scripts}")
        lines.append(f"- **Con SRI:** {report.sri.scripts_with_sri}")
        lines.append(f"- **Sin SRI:** {len(report.sri.scripts_without_sri)}")
        lines.append("")

    # ── Mixed Content ────────────────────────────────────────
    if report.mixed_content:
        total = (
            len(report.mixed_content.mixed_scripts)
            + len(report.mixed_content.mixed_styles)
            + len(report.mixed_content.mixed_images)
        )
        if total > 0:
            lines.append("## Contenido Mixto")
            lines.append("")
            lines.append(f"- **Scripts HTTP:** {len(report.mixed_content.mixed_scripts)}")
            lines.append(f"- **Styles HTTP:** {len(report.mixed_content.mixed_styles)}")
            lines.append(f"- **Imágenes HTTP:** {len(report.mixed_content.mixed_images)}")
            lines.append("")

    # ── Directory Listing ────────────────────────────────────
    if report.directory_listing and report.directory_listing.listings_found:
        lines.append("## Directory Listing")
        lines.append("")
        lines.append(f"- **Rutas con listing:** {', '.join(report.directory_listing.listings_found)}")
        lines.append("")

    # ── HTML Leaks ───────────────────────────────────────────
    if report.html_leaks:
        has_data = (
            report.html_leaks.comments_found > 0
            or report.html_leaks.versions_found
            or report.html_leaks.emails_found
        )
        if has_data:
            lines.append("## Fugas en HTML")
            lines.append("")
            lines.append(f"- **Comentarios HTML:** {report.html_leaks.comments_found}")
            if report.html_leaks.versions_found:
                lines.append(f"- **Versiones expuestas:** {', '.join(report.html_leaks.versions_found[:5])}")
            if report.html_leaks.emails_found:
                lines.append(f"- **Emails encontrados:** {', '.join(report.html_leaks.emails_found[:5])}")
            lines.append("")

    # ── Email Security ───────────────────────────────────────
    if report.email_security:
        lines.append("## Seguridad de Email")
        lines.append("")
        lines.append(f"- **SPF:** {'Sí' if report.email_security.has_spf else '**No**'}")
        lines.append(f"- **DMARC:** {'Sí' if report.email_security.has_dmarc else '**No**'}")
        lines.append(f"- **DKIM:** {'Sí' if report.email_security.has_dkim else '**No**'}")
        lines.append("")

    # ── Recomendaciones ──────────────────────────────────────
    critical_high = [
        f for f in report.all_findings
        if f.severity in (Severity.CRITICAL, Severity.HIGH)
    ]
    if critical_high:
        lines.append("## Recomendaciones Prioritarias")
        lines.append("")
        seen_remediations: List[str] = []
        for f in critical_high:
            if f.remediation not in seen_remediations:
                seen_remediations.append(f.remediation)
                label = _SEVERITY_LABELS.get(f.severity, "")
                lines.append(f"1. **[{label}]** {f.remediation}")
        lines.append("")

    # ── Remediaciones detalladas con código ───────────────────
    guides = get_remediations_for_findings(report.all_findings)
    remediation_section = _render_remediation_section(guides)
    if remediation_section:
        lines.append(remediation_section)

    # ── Footer ───────────────────────────────────────────────
    lines.append("---")
    lines.append("*Generado por SOMER 2.0 — Módulo de Ciberseguridad Defensiva*")
    lines.append("")

    return "\n".join(lines)


def _risk_emoji(score: float) -> str:
    """Retorna emoji según nivel de riesgo."""
    if score >= 8.0:
        return "\U0001f534"
    if score >= 5.0:
        return "\U0001f7e0"
    if score >= 3.0:
        return "\U0001f7e1"
    return "\U0001f7e2"
