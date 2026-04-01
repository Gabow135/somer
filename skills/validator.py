"""Validación de skills."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

from shared.errors import SkillValidationError
from shared.types import SkillMeta

logger = logging.getLogger(__name__)


def validate_skill(skill: SkillMeta) -> List[str]:
    """Valida un skill y retorna lista de warnings.

    Returns:
        Lista de warnings (vacía si todo OK).

    Raises:
        SkillValidationError: Si hay errores críticos.
    """
    warnings: List[str] = []

    if not skill.name:
        raise SkillValidationError("Skill sin nombre")

    if not skill.description:
        warnings.append(f"{skill.name}: sin descripción")

    if not skill.triggers:
        warnings.append(f"{skill.name}: sin triggers definidos")

    if not skill.tools:
        warnings.append(f"{skill.name}: sin tools definidos")

    return warnings


def validate_skill_directory(path: Path) -> Tuple[int, int, List[str]]:
    """Valida un directorio de skills.

    Returns:
        Tuple de (skills_válidos, skills_con_errores, lista_de_errores).
    """
    valid = 0
    errors_list: List[str] = []

    skill_file = path / "SKILL.md"
    if not skill_file.exists():
        errors_list.append(f"{path.name}: falta SKILL.md")
        return 0, 1, errors_list

    from skills.loader import load_skill_file

    try:
        meta = load_skill_file(skill_file)
        warnings = validate_skill(meta)
        if warnings:
            errors_list.extend(warnings)
        valid = 1
    except (SkillValidationError, Exception) as exc:
        errors_list.append(f"{path.name}: {exc}")

    return valid, len(errors_list), errors_list
