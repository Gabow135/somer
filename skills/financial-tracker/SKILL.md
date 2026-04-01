---
name: financial-tracker
description: "Registro de gastos e ingresos — tracking financiero personal/empresarial desde Telegram. Resúmenes y exportación a Excel."
version: "1.0.0"
triggers:
  - gasté
  - gasto
  - ingreso
  - cobré
  - pagué
  - facturé
  - registrar gasto
  - registrar ingreso
  - cuánto he gastado
  - resumen financiero
  - balance del mes
  - finanzas
  - presupuesto
  - financial
  - expense
  - income
  - cuánto llevo gastado
  - reporte de gastos
  - reporte financiero
  - deuda
  - me deben
  - le debo a
tags:
  - finance
  - expenses
  - income
  - budget
  - tracking
  - money
  - business
category: business
enabled: true
---

# Skill: Financial Tracker

Registro financiero personal y empresarial — gastos, ingresos, deudas y presupuestos desde Telegram.

## Reglas

1. **Persistencia en SQLite** — datos en `~/.somer/finance.db`.
2. **Categorización automática** — detecta categoría del gasto/ingreso por contexto.
3. **Moneda configurable** — soporta USD, MXN, EUR, etc.
4. **Privacidad total** — datos nunca salen del dispositivo.

## Cuándo Usar

- "Gasté $50 en hosting"
- "Ingreso $2000 del cliente Acme"
- "¿Cuánto he gastado este mes?"
- "Resumen financiero de marzo"
- "¿Cuánto me debe Juan?"
- "Presupuesto mensual de $5000 para marketing"
- "Exportar gastos del mes a Excel"

## Tools Disponibles

- `finance_add_expense` — Registrar gasto (monto, categoría, descripción, fecha, método de pago)
- `finance_add_income` — Registrar ingreso (monto, fuente/cliente, categoría, descripción)
- `finance_add_debt` — Registrar deuda (quién debe, monto, concepto, dirección: me_deben/debo)
- `finance_get_summary` — Resumen por período (día/semana/mes/año): ingresos, gastos, balance
- `finance_by_category` — Desglose de gastos/ingresos por categoría
- `finance_list_debts` — Listar deudas pendientes (a favor y en contra)
- `finance_set_budget` — Definir presupuesto mensual por categoría
- `finance_export` — Exportar datos a Excel con gráficos

## Categorías Default

**Gastos**: hosting, software, comida, transporte, oficina, marketing, freelancer, impuestos, otros
**Ingresos**: freelance, consultoría, producto, proyecto, salario, inversión, otros

## Integración con Otras Skills

- **crm-lite**: Vincular ingresos a clientes (auto-match por nombre)
- **daily-briefing**: Balance y gastos del día en el briefing
- **report-generator**: Generar reportes financieros PDF/Excel
- **meeting-notes**: Extraer compromisos económicos de notas de reunión

## Formato de Respuesta

**Usar plantilla `TPL-FINANCIAL`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
FINANZAS — Marzo 2026 | 26/Mar/2026

BALANCE
  Ingresos:   $12,500.00
  Gastos:     $4,230.00
  Balance:    +$8,270.00

TOP GASTOS
  1. Hosting/Infra:  $1,200.00  (28%)
  2. Software:       $800.00    (19%)
  3. Marketing:      $650.00    (15%)

TOP INGRESOS
  1. Cliente Acme:   $5,000.00  (40%)
  2. Freelance:      $4,500.00  (36%)
  3. Consultoría:    $3,000.00  (24%)

DEUDAS
  A favor:    $1,500.00 (2 pendientes)
  En contra:  $0.00 (0 pendientes)

PRESUPUESTOS
  [!]  Marketing: $650.00/$1,000.00 (65%)
  [OK] Software:  $800.00/$2,000.00 (40%)

---
Fuente: SOMER Finance | DB: ~/.somer/finance.db
```

Al registrar un gasto/ingreso individual:
```
FINANZAS — Gasto registrado | 26/Mar/2026

  Tipo:       Gasto
  Monto:      $50.00
  Categoría:  Hosting
  Descripción: DigitalOcean droplet
  Método:     Tarjeta

---
Fuente: SOMER Finance | DB: ~/.somer/finance.db
```
