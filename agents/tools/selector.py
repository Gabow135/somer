"""Smart tool selection — picks relevant tools based on message content.

Reduces token usage by only sending relevant tools to the LLM
instead of all registered tools on every request.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Tool groups by category
TOOL_GROUPS: Dict[str, Dict[str, object]] = {
    "security": {
        "keywords": [
            "seguridad", "security", "pentest", "vulnerabilidad", "escaneo",
            "scan", "exploit", "audit", "ssl", "header", "cookie", "xss",
            "sqli", "ssti", "waf", "compliance", "owasp", "pci", "gdpr",
        ],
        "tools": [
            "security_scan", "check_headers", "check_ssl", "check_cookies",
            "discover_tech", "dns_lookup", "scan_ports", "check_http_methods",
            "check_https_redirect", "check_sri", "check_mixed_content",
            "check_directory_listing", "check_html_leaks", "analyze_csp",
            "check_email_security", "run_security_exploits",
            "generate_security_report", "full_pentest", "pentest_plan",
            "pentest_recon", "pentest_scan", "pentest_exploit",
            "pentest_evidence", "pentest_report", "check_sqli",
            "check_admin_panels", "enumerate_subdomains", "detect_waf",
            "check_session_management", "check_request_smuggling",
            "check_ssti", "check_path_traversal", "check_info_disclosure",
            "analyze_jwt", "run_advanced_exploits", "run_single_exploit",
            "capture_screenshot", "extract_sensitive_data",
            "build_evidence_chain", "crawl_links",
        ],
    },
    "osint": {
        "keywords": [
            "osint", "investigar", "breach", "filtración", "shodan",
            "social", "corporate",
        ],
        "tools": [
            "osint_full_investigation", "osint_email_breach",
            "osint_domain_exposure", "osint_shodan_lookup",
            "osint_social_profiles", "osint_corporate_intel",
        ],
    },
    "network": {
        "keywords": [
            "ping", "traceroute", "monitor", "online", "certificado",
            "dns", "servidor", "uptime",
        ],
        "tools": [
            "net_full_check", "net_ping", "net_traceroute",
            "net_cert_check", "net_http_check", "net_dns_health",
        ],
    },
    "malware": {
        "keywords": [
            "malware", "virus", "archivo sospechoso", "hash",
            "virustotal", "ioc",
        ],
        "tools": [
            "malware_full_analysis", "malware_hash_check",
            "malware_strings_extract", "malware_metadata",
            "malware_ioc_extract",
        ],
    },
    "compliance": {
        "keywords": [
            "compliance", "cumplimiento", "owasp", "pci", "gdpr", "iso",
        ],
        "tools": [
            "compliance_full_audit", "compliance_owasp_check",
            "compliance_pci_check", "compliance_gdpr_check",
            "compliance_headers_check", "compliance_ssl_check",
        ],
    },
    "crm": {
        "keywords": [
            "contacto", "cliente", "crm", "seguimiento", "pipeline",
            "lead", "followup",
        ],
        "tools": [
            "crm_add_contact", "crm_search_contacts", "crm_add_interaction",
            "crm_get_history", "crm_add_followup", "crm_list_followups",
            "crm_update_pipeline", "crm_dashboard",
        ],
    },
    "finance": {
        "keywords": [
            "gasto", "ingreso", "deuda", "balance", "presupuesto",
            "financiero", "gasté", "pagué", "cobré",
        ],
        "tools": [
            "finance_add_expense", "finance_add_income", "finance_add_debt",
            "finance_get_summary", "finance_by_category", "finance_list_debts",
            "finance_set_budget",
        ],
    },
    "meetings": {
        "keywords": [
            "reunión", "meeting", "minuta", "action item", "acuerdo",
        ],
        "tools": [
            "meeting_process_notes", "meeting_dispatch_actions",
            "meeting_list_actions", "meeting_search",
        ],
    },
    "bookmarks": {
        "keywords": [
            "bookmark", "guardar link", "guardar url", "link guardado",
        ],
        "tools": [
            "bookmark_save", "bookmark_search", "bookmark_list",
            "bookmark_delete", "bookmark_export",
        ],
    },
    "sri": {
        "keywords": [
            "sri", "obligaciones", "tributario", "ruc", "impuestos",
        ],
        "tools": [
            "sri_check_obligations", "sri_save_credentials",
            "sri_check_user", "sri_check_all_users",
        ],
    },
    "coding": {
        "keywords": [
            "código", "code", "implementar", "refactorizar", "debug",
            "test", "programar", "fix", "bug",
        ],
        "tools": [
            "delegate_coding", "delegate_review", "delegate_debug",
            "delegate_test_gen",
        ],
    },
    "knowledge": {
        "keywords": [
            "knowledge", "grafo", "relación", "entidad", "kg",
        ],
        "tools": [
            "kg_add", "kg_query", "kg_delete",
        ],
    },
    "self_improve": {
        "keywords": [
            "mejorar", "improve", "parche", "patch", "credencial",
            "skill", "restart", "lesson",
        ],
        "tools": [
            "scan_skills", "detect_credentials", "patch_file",
            "revert_patch", "validate_change", "restart_service",
            "self_improve_status", "check_skill_deps", "lesson_save",
            "lesson_recall", "lesson_check",
        ],
    },
    "tasks": {
        "keywords": [
            "tarea background", "task", "cola", "queue",
        ],
        "tools": [
            "task_submit", "task_status", "task_cancel", "task_stats",
        ],
    },
}

# Tools that should ALWAYS be available (essential for any request)
CORE_TOOLS: Set[str] = {
    "http_request",
    "generate_report",
    "get_download_link",
    "shell_exec",
    "shell_which",
    "code_interpreter",
    "sql_query",
    "sql_schema",
    "research",
    "analyze_data",
    "plan_task",
    "agent_messaging",
    "episodic_recall",
    "episodic_save",
    "briefing_generate",
}


def select_tools(
    message: str,
    total_registered: int = 0,
    max_tools: int = 40,
) -> Optional[Set[str]]:
    """Select relevant tools based on message content.

    Returns set of tool names to include, or None to include all tools.
    If the message is ambiguous or matches multiple groups, returns more tools.

    Args:
        message: The user message to analyze.
        total_registered: Total number of registered tools (for logging).
        max_tools: Maximum number of tools to select (soft limit).

    Returns:
        Set of tool names, or None to use all tools.
    """
    if not message or not message.strip():
        return None

    msg_lower = message.lower()
    matched_groups: List[str] = []

    for group_name, group_info in TOOL_GROUPS.items():
        keywords = group_info["keywords"]
        assert isinstance(keywords, list)
        for keyword in keywords:
            if keyword in msg_lower:
                matched_groups.append(group_name)
                break

    # If no specific group matched, return None (use all tools)
    if not matched_groups:
        return None

    # Build tool set: core + matched groups
    selected: Set[str] = set(CORE_TOOLS)
    for group_name in matched_groups:
        tools = TOOL_GROUPS[group_name]["tools"]
        assert isinstance(tools, list)
        selected.update(tools)

    logger.info(
        "Tool selection: %d tools for groups: %s (total registered: %d)",
        len(selected),
        matched_groups,
        total_registered,
    )

    return selected
