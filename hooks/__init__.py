"""Sistema de hooks de SOMER 2.0.

Provee dos subsistemas complementarios:

- **loader** (HookManager): Gestion de hooks de lifecycle con carga dinamica
  desde configuracion. Orientado a hooks de usuario cargados por modulo.

- **internal**: Sistema de eventos internos inspirado en OpenClaw.
  Registro global, tipo:accion, prioridad, contextos tipados y mappers
  de mensajes. Para hooks del motor cognitivo y canales.
"""
