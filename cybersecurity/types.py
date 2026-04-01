"""Tipos Pydantic v2 para escaneos de ciberseguridad."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """Niveles de severidad para hallazgos de seguridad."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ExploitCategory(str, Enum):
    """Categoría de exploit según tipo de vulnerabilidad."""
    INJECTION = "injection"
    AUTH = "authentication"
    SESSION = "session"
    CRYPTO = "cryptography"
    DISCLOSURE = "information-disclosure"
    MISCONFIGURATION = "misconfiguration"
    INPUT_VALIDATION = "input-validation"


class PentestPhase(str, Enum):
    """Fases de un pentest."""
    RECON = "recon"
    SCAN = "scan"
    EXPLOIT = "exploit"
    EVIDENCE = "evidence"
    REPORT = "report"


class RequestLog(BaseModel):
    """Log de un intercambio HTTP request/response."""
    method: str = "GET"
    url: str = ""
    request_headers: Dict[str, str] = Field(default_factory=dict)
    request_body: Optional[str] = None
    response_status: int = 0
    response_headers: Dict[str, str] = Field(default_factory=dict)
    response_body: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class EvidenceChainLink(BaseModel):
    """Un eslabón en la cadena de evidencia."""
    phase: PentestPhase
    source_id: str
    description: str
    data_ref: Optional[str] = None


class EvidenceChain(BaseModel):
    """Cadena de evidencia que conecta findings con exploits."""
    target_url: str = ""
    links: List[EvidenceChainLink] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class SubdomainResult(BaseModel):
    """Resultado de enumeración de subdominios."""
    subdomain: str
    source: str = ""
    resolves: bool = False
    ip: Optional[str] = None


class WAFDetectionResult(BaseModel):
    """Resultado de detección de WAF."""
    detected: bool = False
    waf_name: str = ""
    confidence: str = "low"
    bypass_suggestions: List[str] = Field(default_factory=list)
    findings: List["Finding"] = Field(default_factory=list)


class JWTAnalysisResult(BaseModel):
    """Resultado de análisis de JWT."""
    token_found: bool = False
    algorithm: str = ""
    header: Dict[str, Any] = Field(default_factory=dict)
    claims: Dict[str, Any] = Field(default_factory=dict)
    weaknesses: List[str] = Field(default_factory=list)
    findings: List["Finding"] = Field(default_factory=list)


class PhaseResult(BaseModel):
    """Resultado de una fase del pentest."""
    phase: PentestPhase
    success: bool = False
    duration_secs: float = 0.0
    data: Dict[str, Any] = Field(default_factory=dict)
    findings_count: int = 0
    error: Optional[str] = None


class PentestPlan(BaseModel):
    """Plan de engagement de pentesting."""
    target_url: str
    hostname: str = ""
    scope: str = "full"
    phases: List[PentestPhase] = Field(default_factory=lambda: [
        PentestPhase.RECON, PentestPhase.SCAN,
        PentestPhase.EXPLOIT, PentestPhase.EVIDENCE,
        PentestPhase.REPORT,
    ])
    workspace_path: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    phase_results: Dict[str, PhaseResult] = Field(default_factory=dict)


class Finding(BaseModel):
    """Un hallazgo individual de seguridad."""
    check_id: str
    severity: Severity
    title: str
    detail: str
    remediation: str
    evidence: str = ""
    cwe: Optional[str] = None


class HeaderAnalysis(BaseModel):
    """Resultado del análisis de headers de seguridad."""
    present: Dict[str, str] = Field(default_factory=dict)
    missing: List[str] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)


class SSLAnalysis(BaseModel):
    """Resultado del análisis SSL/TLS."""
    valid: bool = False
    issuer: str = ""
    subject: str = ""
    expires: str = ""
    protocol: str = ""
    cipher: str = ""
    san: List[str] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)


class CookieInfo(BaseModel):
    """Información de una cookie individual."""
    name: str
    secure: bool = False
    httponly: bool = False
    samesite: str = ""
    path: str = "/"


class CookieAnalysis(BaseModel):
    """Resultado del análisis de cookies."""
    cookies: List[CookieInfo] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)


class TechFingerprint(BaseModel):
    """Resultado de fingerprinting tecnológico."""
    technologies: List[Dict[str, str]] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)


class DNSResult(BaseModel):
    """Resultado de consulta DNS."""
    records: Dict[str, List[str]] = Field(default_factory=dict)
    findings: List[Finding] = Field(default_factory=list)


class DiscoveredPath(BaseModel):
    """Una ruta descubierta."""
    path: str
    status_code: int
    content_length: int = 0


class PathDiscoveryResult(BaseModel):
    """Resultado de descubrimiento de rutas."""
    found: List[DiscoveredPath] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)


class CORSAnalysis(BaseModel):
    """Resultado del análisis CORS."""
    origin_reflected: bool = False
    allows_credentials: bool = False
    allow_origin: str = ""
    allow_methods: str = ""
    findings: List[Finding] = Field(default_factory=list)


class FormInfo(BaseModel):
    """Información de un formulario."""
    action: str = ""
    method: str = "GET"
    has_csrf_token: bool = False
    password_autocomplete: bool = False
    external_action: bool = False


class FormAnalysis(BaseModel):
    """Resultado del análisis de formularios."""
    forms: List[FormInfo] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)


class XSSResult(BaseModel):
    """Resultado del análisis de reflexión XSS."""
    tested_params: int = 0
    reflected_params: List[str] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)


class OpenPort(BaseModel):
    """Un puerto abierto detectado."""
    port: int
    service: str = ""


class PortScanResult(BaseModel):
    """Resultado del escaneo de puertos."""
    open_ports: List[OpenPort] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)


class CrawlResult(BaseModel):
    """Resultado del crawling de links."""
    internal_links: List[str] = Field(default_factory=list)
    external_links: List[str] = Field(default_factory=list)
    forms_found: int = 0
    pages_crawled: int = 0
    findings: List[Finding] = Field(default_factory=list)


class OpenRedirectResult(BaseModel):
    """Resultado de check de open redirects."""
    vulnerable_params: List[str] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)


class HttpMethodsAnalysis(BaseModel):
    """Resultado del análisis de métodos HTTP."""
    allowed_methods: List[str] = Field(default_factory=list)
    unsafe_methods: List[str] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)


class HttpsRedirectAnalysis(BaseModel):
    """Resultado del análisis de redirección HTTPS."""
    redirects_to_https: bool = False
    redirect_chain: List[str] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)


class SRIAnalysis(BaseModel):
    """Resultado del análisis de Subresource Integrity."""
    external_scripts: int = 0
    scripts_with_sri: int = 0
    scripts_without_sri: List[str] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)


class MixedContentAnalysis(BaseModel):
    """Resultado del análisis de contenido mixto."""
    mixed_scripts: List[str] = Field(default_factory=list)
    mixed_styles: List[str] = Field(default_factory=list)
    mixed_images: List[str] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)


class DirectoryListingAnalysis(BaseModel):
    """Resultado del análisis de directory listing."""
    paths_tested: List[str] = Field(default_factory=list)
    listings_found: List[str] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)


class HtmlLeaksAnalysis(BaseModel):
    """Resultado del análisis de leaks en HTML."""
    comments_found: int = 0
    versions_found: List[str] = Field(default_factory=list)
    emails_found: List[str] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)


class CSPAnalysis(BaseModel):
    """Resultado del análisis de Content Security Policy."""
    raw_policy: str = ""
    directives: Dict[str, List[str]] = Field(default_factory=dict)
    has_unsafe_inline: bool = False
    has_unsafe_eval: bool = False
    findings: List[Finding] = Field(default_factory=list)


class EmailSecurityAnalysis(BaseModel):
    """Resultado del análisis de seguridad de email (SPF/DMARC/DKIM)."""
    has_spf: bool = False
    has_dmarc: bool = False
    has_dkim: bool = False
    spf_record: str = ""
    dmarc_record: str = ""
    findings: List[Finding] = Field(default_factory=list)


class CodeSnippet(BaseModel):
    """Fragmento de código de remediación para una plataforma."""
    platform: str       # "nginx", "apache", "express", "nextjs", "django", "general"
    language: str       # "nginx", "apache", "javascript", "python", "html"
    code: str
    description: str


class RemediationGuide(BaseModel):
    """Guía de remediación completa para un check_id."""
    check_id: str
    title: str
    explanation: str
    snippets: List[CodeSnippet] = Field(default_factory=list)
    references: List[str] = Field(default_factory=list)


class ScanReport(BaseModel):
    """Reporte completo de escaneo de seguridad."""
    target_url: str
    scan_duration_secs: float = 0.0
    headers: Optional[HeaderAnalysis] = None
    ssl: Optional[SSLAnalysis] = None
    cookies: Optional[CookieAnalysis] = None
    tech: Optional[TechFingerprint] = None
    dns: Optional[DNSResult] = None
    paths: Optional[PathDiscoveryResult] = None
    cors: Optional[CORSAnalysis] = None
    forms: Optional[FormAnalysis] = None
    xss: Optional[XSSResult] = None
    ports: Optional[PortScanResult] = None
    crawl: Optional[CrawlResult] = None
    redirects: Optional[OpenRedirectResult] = None
    http_methods: Optional[HttpMethodsAnalysis] = None
    https_redirect: Optional[HttpsRedirectAnalysis] = None
    sri: Optional[SRIAnalysis] = None
    mixed_content: Optional[MixedContentAnalysis] = None
    directory_listing: Optional[DirectoryListingAnalysis] = None
    html_leaks: Optional[HtmlLeaksAnalysis] = None
    csp: Optional[CSPAnalysis] = None
    email_security: Optional[EmailSecurityAnalysis] = None
    all_findings: List[Finding] = Field(default_factory=list)
    risk_score: float = 0.0

    def collect_findings(self) -> None:
        """Recolecta todos los findings de cada análisis."""
        findings: List[Finding] = []
        for section in (
            self.headers, self.ssl, self.cookies, self.tech,
            self.dns, self.paths, self.cors, self.forms,
            self.xss, self.ports, self.crawl, self.redirects,
            self.http_methods, self.https_redirect, self.sri,
            self.mixed_content, self.directory_listing,
            self.html_leaks, self.csp, self.email_security,
        ):
            if section is not None:
                findings.extend(section.findings)
        self.all_findings = findings


class ExploitEvidence(BaseModel):
    """Evidencia capturada de un exploit PoC."""
    description: str
    screenshot_path: Optional[str] = None
    response_data: Optional[str] = None
    http_status: Optional[int] = None
    request_log: Optional[RequestLog] = None
    data_extracted: Optional[str] = None
    redacted_data: Optional[str] = None


class ExploitResult(BaseModel):
    """Resultado de un exploit PoC individual."""
    exploit_id: str
    finding_check_id: str
    title: str
    success: bool = False
    impact_description: str = ""
    evidence: List[ExploitEvidence] = Field(default_factory=list)
    duration_secs: float = 0.0
    category: Optional[ExploitCategory] = None
    cvss_estimate: Optional[float] = None
    evidence_chain: Optional[EvidenceChain] = None


class ExploitReport(BaseModel):
    """Reporte completo de exploits ejecutados."""
    target_url: str
    total_exploits: int = 0
    successful: int = 0
    failed: int = 0
    results: List[ExploitResult] = Field(default_factory=list)
    workspace_path: Optional[str] = None
    duration_secs: float = 0.0
