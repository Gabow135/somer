"""Infraestructura de SOMER — utilidades de sistema, red, procesos.

Módulos disponibles:
- env: Normalización de entorno y archivos .env
- net: Utilidades de red, retry, backoff, deduplicación
- ports: Sondeo de puertos y detección de procesos
- heartbeat: HeartbeatRunner para turnos LLM periódicos
- system_events: Bus de eventos interno (agente + diagnóstico)
- state_migrations: Migraciones incrementales de estado/config
- runtime_status: Rastreo de uptime, versiones, salud
- gateway_processes: Gestión de procesos del gateway
- file_lock: Bloqueo cooperativo basado en archivos
- secure_random: Generación segura de tokens e IDs
- os_info: Resumen del SO y detección de plataforma
- path_safety: Protección contra path traversal
- restart_sentinel: Coordinación de reinicios entre procesos
- session_cost: Seguimiento de costos por sesión
"""
