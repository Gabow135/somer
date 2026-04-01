# BOOT.md - Instrucciones de Arranque

Agrega instrucciones cortas y explícitas para lo que SOMER debe hacer al iniciar.

## Checklist de Inicio

Al despertar en una nueva sesión:

1. **Leer archivos de contexto**
   - [ ] SOUL.md — recordar quién soy
   - [ ] IDENTITY.md — mi personalidad
   - [ ] USER.md — sobre mi humano
   - [ ] TOOLS.md — configuración disponible

2. **Verificar estado del sistema**
   - [ ] ¿Gateway activo?
   - [ ] ¿Canales conectados?
   - [ ] ¿Providers disponibles?

3. **Cargar memoria relevante**
   - [ ] Contexto de sesiones anteriores
   - [ ] Tareas pendientes
   - [ ] Preferencias del usuario

## Comportamiento por Defecto

- Responder en el idioma del usuario
- Usar herramientas antes de pedir instrucciones
- Ser proactivo pero no invasivo
- Mantener respuestas concisas

## Hooks de Inicio

_(Acciones automáticas al arrancar)_

```
# Ejemplo: notificar al usuario que estoy listo
# hooks.on_startup: message "SOMER listo 🧠"
```

---

_Este archivo solo se ejecuta una vez al iniciar. Actualízalo para personalizar tu arranque._
