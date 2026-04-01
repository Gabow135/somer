"""Schemas de output estructurado para agentes.

Portado de OpenClaw: schema/typebox.ts, schema/clean-for-gemini.ts,
schema/clean-for-xai.ts.

Provee utilidades para definir schemas de output que el LLM debe
seguir, con adaptaciones por provider (Anthropic, OpenAI, Google, xAI).

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Definición de schema ──────────────────────────────────────


class OutputSchema:
    """Define un schema de output estructurado para el agente.

    Portado de OpenClaw: schema/typebox.ts.
    Envuelve un JSON Schema y lo adapta según el provider.
    """

    def __init__(
        self,
        schema: Dict[str, Any],
        *,
        name: str = "output",
        description: str = "",
        strict: bool = True,
    ) -> None:
        """
        Args:
            schema: JSON Schema del output esperado.
            name: Nombre del schema (para logging).
            description: Descripción del schema.
            strict: Si True, el schema es estricto (sin propiedades extra).
        """
        self.schema = schema
        self.name = name
        self.description = description
        self.strict = strict

    def for_provider(self, provider_family: str) -> Dict[str, Any]:
        """Adapta el schema para un provider específico.

        Args:
            provider_family: "anthropic", "openai", "google", "default".

        Returns:
            Schema adaptado para el provider.
        """
        if provider_family == "google":
            return clean_for_gemini(self.schema)
        if provider_family in ("xai",):
            return clean_for_xai(self.schema)
        return self.schema

    def to_anthropic_format(self) -> Dict[str, Any]:
        """Convierte a formato de herramienta de Anthropic para output estructurado."""
        return {
            "name": self.name,
            "description": self.description or f"Structured output: {self.name}",
            "input_schema": self.schema,
        }

    def to_openai_format(self) -> Dict[str, Any]:
        """Convierte a formato de response_format de OpenAI."""
        return {
            "type": "json_schema",
            "json_schema": {
                "name": self.name,
                "schema": self.schema,
                "strict": self.strict,
            },
        }


# ── Limpieza por provider ────────────────────────────────────


def clean_for_gemini(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Limpia un JSON Schema para compatibilidad con Google Gemini.

    Portado de OpenClaw: schema/clean-for-gemini.ts.
    Gemini no soporta ciertas keywords de JSON Schema.

    Reglas:
    - Elimina ``additionalProperties``
    - Elimina ``$schema``
    - Elimina ``title`` en sub-schemas
    - Convierte ``const`` a ``enum`` con un solo valor
    """
    result = copy.deepcopy(schema)
    _clean_gemini_recursive(result, is_root=True)
    return result


def _clean_gemini_recursive(obj: Any, is_root: bool = False) -> None:
    """Limpieza recursiva de schema para Gemini."""
    if not isinstance(obj, dict):
        return

    # Eliminar keywords no soportadas
    for key in ("additionalProperties", "$schema"):
        obj.pop(key, None)

    if not is_root:
        obj.pop("title", None)

    # const → enum
    if "const" in obj:
        obj["enum"] = [obj.pop("const")]

    # Recurrir en propiedades
    properties = obj.get("properties")
    if isinstance(properties, dict):
        for prop_schema in properties.values():
            _clean_gemini_recursive(prop_schema)

    items = obj.get("items")
    if isinstance(items, dict):
        _clean_gemini_recursive(items)

    # anyOf, oneOf, allOf
    for keyword in ("anyOf", "oneOf", "allOf"):
        variants = obj.get(keyword)
        if isinstance(variants, list):
            for variant in variants:
                _clean_gemini_recursive(variant)


def clean_for_xai(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Limpia un JSON Schema para compatibilidad con xAI (Grok).

    Portado de OpenClaw: schema/clean-for-xai.ts.
    xAI tiene limitaciones similares a Gemini.

    Reglas:
    - Elimina ``additionalProperties``
    - Elimina ``$schema``
    """
    result = copy.deepcopy(schema)
    _clean_xai_recursive(result)
    return result


def _clean_xai_recursive(obj: Any) -> None:
    """Limpieza recursiva de schema para xAI."""
    if not isinstance(obj, dict):
        return

    for key in ("additionalProperties", "$schema"):
        obj.pop(key, None)

    properties = obj.get("properties")
    if isinstance(properties, dict):
        for prop_schema in properties.values():
            _clean_xai_recursive(prop_schema)

    items = obj.get("items")
    if isinstance(items, dict):
        _clean_xai_recursive(items)

    for keyword in ("anyOf", "oneOf", "allOf"):
        variants = obj.get(keyword)
        if isinstance(variants, list):
            for variant in variants:
                _clean_xai_recursive(variant)


# ── Schemas comunes ───────────────────────────────────────────


def text_response_schema(
    *,
    max_length: Optional[int] = None,
) -> OutputSchema:
    """Schema para una respuesta de texto simple."""
    props: Dict[str, Any] = {
        "text": {"type": "string", "description": "Respuesta de texto"},
    }
    if max_length is not None:
        props["text"]["maxLength"] = max_length

    return OutputSchema(
        schema={
            "type": "object",
            "properties": props,
            "required": ["text"],
        },
        name="text_response",
        description="Respuesta de texto simple",
    )


def json_response_schema(
    properties: Dict[str, Any],
    *,
    required: Optional[List[str]] = None,
    name: str = "json_response",
    description: str = "",
) -> OutputSchema:
    """Schema para una respuesta JSON estructurada."""
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required

    return OutputSchema(
        schema=schema,
        name=name,
        description=description,
    )
