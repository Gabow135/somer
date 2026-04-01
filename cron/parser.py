"""Parser de expresiones cron con soporte de timezone y strings especiales.

Portado y extendido desde OpenClaw ``schedule.ts`` + ``parse.ts``.
Soporta expresiones cron estándar de 5 campos, strings especiales (@daily, etc.),
ranges con step (1-5/2), y evaluación timezone-aware.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from shared.errors import CronExpressionError

# ── Strings especiales (portados de OpenClaw) ───────────────
SPECIAL_EXPRESSIONS = {
    "@yearly":   "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly":  "0 0 1 * *",
    "@weekly":   "0 0 * * 0",
    "@daily":    "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly":   "0 * * * *",
    "@every_minute": "* * * * *",
}

# ── Nombres de mes/día ──────────────────────────────────────
MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

DOW_NAMES = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}

# ── Límites por campo ──────────────────────────────────────
FIELD_LIMITS: List[Tuple[int, int]] = [
    (0, 59),   # minuto
    (0, 23),   # hora
    (1, 31),   # día del mes
    (1, 12),   # mes
    (0, 6),    # día de la semana (0=domingo)
]

FIELD_NAMES = ["minuto", "hora", "día del mes", "mes", "día de la semana"]


def _replace_names(field_expr: str, names: dict) -> str:
    """Reemplaza nombres por valores numéricos en una expresión de campo."""
    result = field_expr.lower()
    for name, value in names.items():
        result = result.replace(name, str(value))
    return result


def _parse_field(field_expr: str, min_val: int, max_val: int, field_name: str) -> List[int]:
    """Parsea un campo cron y retorna la lista de valores que coinciden.

    Soporta: *, N, */N, N-M, N-M/S, N,M,O y nombres de mes/día.
    """
    field_expr = field_expr.strip()

    # Reemplazar nombres
    if field_name == "mes":
        field_expr = _replace_names(field_expr, MONTH_NAMES)
    elif field_name == "día de la semana":
        field_expr = _replace_names(field_expr, DOW_NAMES)

    values: List[int] = []

    # Lista separada por comas
    for part in field_expr.split(","):
        part = part.strip()
        if not part:
            continue

        step = 1
        if "/" in part:
            range_part, step_str = part.split("/", 1)
            try:
                step = int(step_str)
                if step < 1:
                    raise CronExpressionError(
                        f"Step inválido en campo {field_name}: {part}"
                    )
            except ValueError:
                raise CronExpressionError(
                    f"Step no numérico en campo {field_name}: {part}"
                )
            part = range_part

        if part == "*":
            values.extend(range(min_val, max_val + 1, step))
        elif "-" in part:
            range_parts = part.split("-", 1)
            try:
                lo = int(range_parts[0])
                hi = int(range_parts[1])
            except ValueError:
                raise CronExpressionError(
                    f"Rango inválido en campo {field_name}: {part}"
                )
            if lo < min_val or hi > max_val:
                raise CronExpressionError(
                    f"Rango fuera de límites en campo {field_name}: {part} "
                    f"(permitido: {min_val}-{max_val})"
                )
            values.extend(range(lo, hi + 1, step))
        else:
            try:
                val = int(part)
            except ValueError:
                raise CronExpressionError(
                    f"Valor no numérico en campo {field_name}: {part}"
                )
            if val < min_val or val > max_val:
                raise CronExpressionError(
                    f"Valor fuera de límites en campo {field_name}: {val} "
                    f"(permitido: {min_val}-{max_val})"
                )
            if step > 1:
                values.extend(range(val, max_val + 1, step))
            else:
                values.append(val)

    return sorted(set(values))


def parse_cron_expression(expression: str) -> List[List[int]]:
    """Parsea una expresión cron completa.

    Acepta expresiones de 5 campos o strings especiales (@daily, etc.).

    Args:
        expression: Expresión cron o string especial.

    Returns:
        Lista de 5 listas con los valores posibles para cada campo.

    Raises:
        CronExpressionError: Si la expresión es inválida.
    """
    expr = expression.strip()

    # Strings especiales
    if expr.startswith("@"):
        normalized = SPECIAL_EXPRESSIONS.get(expr.lower())
        if normalized is None:
            raise CronExpressionError(
                f"Expresión especial desconocida: {expr}. "
                f"Válidas: {', '.join(SPECIAL_EXPRESSIONS.keys())}"
            )
        expr = normalized

    parts = expr.split()
    if len(parts) != 5:
        raise CronExpressionError(
            f"Expresión cron inválida (se esperan 5 campos): {expression}"
        )

    fields: List[List[int]] = []
    for i, (part, (min_val, max_val)) in enumerate(zip(parts, FIELD_LIMITS)):
        try:
            parsed = _parse_field(part, min_val, max_val, FIELD_NAMES[i])
            if not parsed:
                raise CronExpressionError(
                    f"Campo {FIELD_NAMES[i]} vacío tras parseo: {part}"
                )
            fields.append(parsed)
        except CronExpressionError:
            raise
        except Exception as exc:
            raise CronExpressionError(
                f"Error al parsear campo {FIELD_NAMES[i]}: {part}"
            ) from exc

    return fields


def matches_cron(expression: str, now: datetime) -> bool:
    """Evalúa si una expresión cron coincide con el momento actual.

    Formato: minute hour day_of_month month day_of_week
    Ejemplo: '*/5 * * * *' = cada 5 minutos

    Soporta strings especiales (@daily, @hourly, etc.) y
    nombres de mes/día (jan, feb, mon, tue...).

    Args:
        expression: Expresión cron.
        now: Momento a evaluar.

    Returns:
        True si la expresión coincide con el momento.
    """
    fields = parse_cron_expression(expression)
    minutes, hours, days, months, weekdays = fields

    # isoweekday: 1=lunes, 7=domingo → convertir a 0=domingo
    weekday = now.isoweekday() % 7

    return (
        now.minute in minutes
        and now.hour in hours
        and now.day in days
        and now.month in months
        and weekday in weekdays
    )


def next_cron_datetime(
    expression: str,
    after: datetime,
    *,
    max_iterations: int = 527040,
) -> Optional[datetime]:
    """Calcula la próxima fecha/hora que coincide con la expresión cron.

    Portado de ``computeNextRunAtMs`` en OpenClaw ``schedule.ts``.

    Args:
        expression: Expresión cron.
        after: Buscar después de este momento.
        max_iterations: Máximo de minutos a explorar (default: 1 año).

    Returns:
        Próximo datetime que coincide, o None si no se encuentra.
    """
    fields = parse_cron_expression(expression)
    minutes, hours, days, months, weekdays = fields

    # Avanzar al siguiente minuto
    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)

    for _ in range(max_iterations):
        weekday = candidate.isoweekday() % 7

        if (
            candidate.month in months
            and candidate.day in days
            and weekday in weekdays
            and candidate.hour in hours
            and candidate.minute in minutes
        ):
            return candidate

        candidate += timedelta(minutes=1)

    return None


def prev_cron_datetime(
    expression: str,
    before: datetime,
    *,
    max_iterations: int = 527040,
) -> Optional[datetime]:
    """Calcula la fecha/hora anterior que coincide con la expresión cron.

    Portado de ``computePreviousRunAtMs`` en OpenClaw ``schedule.ts``.

    Args:
        expression: Expresión cron.
        before: Buscar antes de este momento.
        max_iterations: Máximo de minutos a explorar (default: 1 año).

    Returns:
        Datetime anterior que coincide, o None si no se encuentra.
    """
    fields = parse_cron_expression(expression)
    minutes, hours, days, months, weekdays = fields

    # Retroceder al minuto anterior
    candidate = before.replace(second=0, microsecond=0) - timedelta(minutes=1)

    for _ in range(max_iterations):
        weekday = candidate.isoweekday() % 7

        if (
            candidate.month in months
            and candidate.day in days
            and weekday in weekdays
            and candidate.hour in hours
            and candidate.minute in minutes
        ):
            return candidate

        candidate -= timedelta(minutes=1)

    return None


def parse_absolute_time(input_str: str) -> Optional[float]:
    """Parsea un timestamp absoluto (epoch ms, ISO 8601).

    Portado de ``parseAbsoluteTimeMs`` en OpenClaw ``parse.ts``.

    Args:
        input_str: String con timestamp.

    Returns:
        Timestamp en segundos epoch, o None si no se puede parsear.
    """
    raw = input_str.strip()
    if not raw:
        return None

    # Epoch numérico (asumimos milisegundos si > 1e12)
    if re.match(r"^\d+$", raw):
        n = int(raw)
        if n > 0:
            # Heurística: si es muy grande, es milisegundos
            return n / 1000.0 if n > 1e12 else float(n)

    # ISO 8601
    try:
        # Normalizar si no tiene timezone
        if not re.search(r"(Z|[+-]\d{2}:?\d{2})$", raw, re.IGNORECASE):
            if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
                raw = f"{raw}T00:00:00Z"
            elif re.match(r"^\d{4}-\d{2}-\d{2}T", raw):
                raw = f"{raw}Z"
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, OverflowError):
        return None


def is_top_of_hour_cron(expression: str) -> bool:
    """Detecta si una expresión cron se ejecuta al inicio de cada hora.

    Portado de ``isRecurringTopOfHourCronExpr`` en OpenClaw ``stagger.ts``.

    Args:
        expression: Expresión cron normalizada.

    Returns:
        True si se ejecuta en minuto 0 de horas con wildcard.
    """
    expr = expression.strip()
    if expr.startswith("@"):
        normalized = SPECIAL_EXPRESSIONS.get(expr.lower())
        if normalized:
            expr = normalized
        else:
            return False

    parts = expr.split()
    if len(parts) == 5:
        return parts[0] == "0" and "*" in parts[1]
    return False


def describe_cron(expression: str) -> str:
    """Genera una descripción legible de una expresión cron.

    Args:
        expression: Expresión cron.

    Returns:
        Descripción en español.
    """
    expr = expression.strip()

    # Strings especiales
    special_descriptions = {
        "@yearly": "una vez al año (1 de enero a medianoche)",
        "@annually": "una vez al año (1 de enero a medianoche)",
        "@monthly": "una vez al mes (día 1 a medianoche)",
        "@weekly": "una vez por semana (domingos a medianoche)",
        "@daily": "una vez al día (a medianoche)",
        "@midnight": "una vez al día (a medianoche)",
        "@hourly": "una vez por hora (minuto 0)",
        "@every_minute": "cada minuto",
    }
    if expr.lower() in special_descriptions:
        return special_descriptions[expr.lower()]

    parts = expr.split()
    if len(parts) != 5:
        return f"expresión cron: {expr}"

    minute, hour, day, month, weekday = parts

    desc_parts: List[str] = []

    if minute == "*" and hour == "*":
        desc_parts.append("cada minuto")
    elif minute.startswith("*/"):
        desc_parts.append(f"cada {minute[2:]} minutos")
    elif hour == "*":
        desc_parts.append(f"en el minuto {minute} de cada hora")
    else:
        desc_parts.append(f"a las {hour}:{minute.zfill(2)}")

    if day != "*":
        desc_parts.append(f"el día {day}")
    if month != "*":
        desc_parts.append(f"del mes {month}")
    if weekday != "*":
        day_names = ["domingo", "lunes", "martes", "miércoles",
                     "jueves", "viernes", "sábado"]
        try:
            dow = int(weekday)
            if 0 <= dow <= 6:
                desc_parts.append(f"los {day_names[dow]}")
        except ValueError:
            desc_parts.append(f"día de semana {weekday}")

    return " ".join(desc_parts)
