"""Utilidades para el módulo de ciberseguridad."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse


def normalize_url(url: str) -> str:
    """Normaliza una URL agregando https:// si falta esquema."""
    url = url.strip()
    if not url:
        return url
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    return url


def extract_hostname(url: str) -> str:
    """Extrae el hostname de una URL."""
    parsed = urlparse(normalize_url(url))
    return parsed.hostname or ""


def is_same_origin(url1: str, url2: str) -> bool:
    """Compara si dos URLs comparten el mismo origen (scheme+host+port)."""
    p1 = urlparse(normalize_url(url1))
    p2 = urlparse(normalize_url(url2))
    return (p1.scheme == p2.scheme and p1.netloc == p2.netloc)


def parse_html_forms(html: str) -> List[Dict[str, str]]:
    """Extrae formularios de HTML con regex.

    Retorna lista de dicts con keys: action, method, inputs.
    """
    forms: List[Dict[str, str]] = []
    form_pattern = re.compile(
        r"<form\b([^>]*)>(.*?)</form>",
        re.IGNORECASE | re.DOTALL,
    )
    for match in form_pattern.finditer(html):
        attrs_str = match.group(1)
        body = match.group(2)

        action = _extract_attr(attrs_str, "action") or ""
        method = _extract_attr(attrs_str, "method") or "GET"

        # Buscar inputs
        input_names: List[str] = []
        for inp in re.finditer(r"<input\b([^>]*)>", body, re.IGNORECASE):
            name = _extract_attr(inp.group(1), "name")
            if name:
                input_names.append(name)

        forms.append({
            "action": action,
            "method": method.upper(),
            "inputs": ",".join(input_names),
        })
    return forms


def parse_html_links(html: str, base_url: str) -> List[str]:
    """Extrae enlaces href de HTML y los resuelve contra base_url."""
    links: List[str] = []
    for match in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\']', html, re.IGNORECASE):
        href = match.group(1).strip()
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        resolved = urljoin(base_url, href)
        links.append(resolved)
    return links


def sanitize_for_display(text: str, max_len: int = 200) -> str:
    """Trunca y limpia texto para mostrar en reportes."""
    if not text:
        return ""
    text = text.replace("\n", " ").replace("\r", "").strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def _extract_attr(attrs_str: str, attr_name: str) -> Optional[str]:
    """Extrae el valor de un atributo HTML."""
    pattern = re.compile(
        rf'{attr_name}\s*=\s*["\']([^"\']*)["\']',
        re.IGNORECASE,
    )
    m = pattern.search(attrs_str)
    return m.group(1) if m else None


def parse_set_cookie(header_value: str) -> Tuple[str, Dict[str, str]]:
    """Parsea un header Set-Cookie y retorna (nombre, atributos)."""
    parts = [p.strip() for p in header_value.split(";")]
    if not parts:
        return "", {}

    # Primer parte es name=value
    name_val = parts[0]
    name = name_val.split("=", 1)[0].strip() if "=" in name_val else name_val.strip()

    attrs: Dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            k, v = part.split("=", 1)
            attrs[k.strip().lower()] = v.strip()
        else:
            attrs[part.strip().lower()] = "true"

    return name, attrs
