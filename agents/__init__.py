"""Módulo de agentes de SOMER 2.0.

Portado de OpenClaw: src/agents/.

Subcomponentes:
- runner: Motor de ejecución de agentes (multi-turn, tools, streaming)
- context_window: Guard de ventana de contexto
- compaction: Compactación de contexto con summarización
- model_fallback: Cadena de fallback entre modelos/providers
- subagent: Sistema de sub-agentes (registry, spawn, depth)
- agent_command: Parsing y ejecución de comandos de agente
- auth_profiles: Gestión de perfiles de autenticación con rotación
- credential_interceptor: Detección proactiva de credenciales
- schema: Schemas de output estructurado
- tools/: Sistema de tools (registry, loop detection, perfiles)
"""
