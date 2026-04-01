---
name: sri-obligations
description: >
  Consulta obligaciones tributarias en el SRI Ecuador (srienlinea.sri.gob.ec).
  Inicia sesión con las credenciales configuradas y extrae la lista de obligaciones
  pendientes del dashboard. Usar cuando el usuario pida revisar obligaciones del SRI,
  deudas tributarias, o estado de cumplimiento fiscal en Ecuador.
triggers:
  - sri
  - obligaciones sri
  - deudas sri
  - sri ecuador
  - tributario
env:
  - SRI_RUC
  - SRI_PASSWORD
---

# SRI Obligations

Consulta obligaciones tributarias del SRI Ecuador via automatización web con Playwright.

## Cuándo Usar

- "Revisa mis obligaciones del SRI"
- "¿Qué debo al SRI?"
- "Consulta el estado tributario"
- "Verifica mis obligaciones pendientes en el SRI"

## Cómo Funciona

1. Navega a https://srienlinea.sri.gob.ec/sri-en-linea/inicio/NAT
2. Click en "Iniciar Sesión"
3. Ingresa credenciales desde variables de entorno
4. Extrae la lista de obligaciones del dashboard
5. Retorna resultado formateado

## Credenciales Requeridas

```bash
SRI_RUC=tu_ruc_o_cedula
SRI_PASSWORD=tu_password
```

## Ejecutar Script

```bash
python3 skills/sri-obligations/scripts/sri_check.py
```

## Formato de Respuesta

Usa TPL-ACTION con las obligaciones encontradas en SALIDA.
