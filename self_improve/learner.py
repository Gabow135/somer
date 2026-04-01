"""Auto-aprendizaje de patrones de credenciales desde SKILL.md files.

Escanea los skills del proyecto, extrae qué variables de entorno necesitan,
y persiste patrones aprendidos en ~/.somer/learned_patterns.json para que
el detector de credenciales los use automáticamente.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from self_improve.paths import get_somer_home, list_project_skills
from skills.loader import parse_skill_md

logger = logging.getLogger(__name__)

LEARNED_FILE = "learned_patterns.json"


@dataclass
class LearnedPattern:
    """Patrón de credencial aprendido de un SKILL.md."""
    env_var: str
    service: str
    description: str
    kind: str = "api_key"  # api_key, token, secret, id
    source_skill: str = ""
    learned_at: float = 0.0
    context_keywords: List[str] = field(default_factory=list)


@dataclass
class LearnedStore:
    """Almacén persistente de patrones aprendidos."""
    patterns: List[LearnedPattern] = field(default_factory=list)
    last_scan: float = 0.0
    skills_scanned: int = 0
    version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "last_scan": self.last_scan,
            "skills_scanned": self.skills_scanned,
            "patterns": [asdict(p) for p in self.patterns],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LearnedStore":
        patterns = [
            LearnedPattern(**p) for p in data.get("patterns", [])
        ]
        return cls(
            patterns=patterns,
            last_scan=data.get("last_scan", 0.0),
            skills_scanned=data.get("skills_scanned", 0),
            version=data.get("version", 1),
        )


class PatternLearner:
    """Aprende patrones de credenciales escaneando SKILL.md files.

    Uso:
        learner = PatternLearner()
        new_count = learner.scan_and_learn()
        patterns = learner.get_patterns()
    """

    def __init__(self) -> None:
        self._store_path = get_somer_home() / LEARNED_FILE
        self._store = self._load()

    def _load(self) -> LearnedStore:
        """Carga patrones persistidos."""
        if not self._store_path.exists():
            return LearnedStore()
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
            return LearnedStore.from_dict(data)
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            logger.warning("Error cargando learned_patterns: %s", exc)
            return LearnedStore()

    def _save(self) -> None:
        """Persiste patrones a disco."""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._store_path.write_text(
            json.dumps(self._store.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def scan_and_learn(self) -> int:
        """Escanea todos los SKILL.md y aprende patrones nuevos.

        Returns:
            Cantidad de patrones nuevos aprendidos.
        """
        skills = list_project_skills()
        if not skills:
            logger.info("No se encontraron skills para escanear")
            return 0

        existing_vars = {p.env_var for p in self._store.patterns}
        new_count = 0

        for skill_path in skills:
            try:
                patterns = self._extract_from_skill(skill_path)
                for pat in patterns:
                    if pat.env_var not in existing_vars:
                        self._store.patterns.append(pat)
                        existing_vars.add(pat.env_var)
                        new_count += 1
                        logger.info(
                            "Patrón aprendido: %s (%s) desde %s",
                            pat.env_var, pat.service, pat.source_skill,
                        )
            except Exception as exc:
                logger.debug("Error procesando %s: %s", skill_path, exc)

        self._store.last_scan = time.time()
        self._store.skills_scanned = len(skills)
        self._save()

        return new_count

    def get_patterns(self) -> List[LearnedPattern]:
        """Retorna todos los patrones aprendidos."""
        return list(self._store.patterns)

    def get_context_keywords(self) -> Dict[str, List[str]]:
        """Genera mapa de keywords de contexto para el detector.

        Returns:
            Dict[env_var, [regex_patterns]] listo para usar en el detector.
        """
        result: Dict[str, List[str]] = {}
        for pat in self._store.patterns:
            if pat.context_keywords:
                result[pat.env_var] = pat.context_keywords
            else:
                # Generar keywords automáticos desde el nombre del servicio
                service = pat.service.lower().replace("-", "[\\s_-]*")
                kind_kw = self._kind_to_keyword(pat.kind)
                result[pat.env_var] = [
                    f"{service}[\\s_-]*(?:{kind_kw})",
                ]
        return result

    @property
    def last_scan_age_hours(self) -> Optional[float]:
        """Horas desde el último escaneo."""
        if self._store.last_scan <= 0:
            return None
        return (time.time() - self._store.last_scan) / 3600

    @property
    def stats(self) -> Dict[str, Any]:
        """Estadísticas del learner."""
        return {
            "total_patterns": len(self._store.patterns),
            "skills_scanned": self._store.skills_scanned,
            "last_scan": self._store.last_scan,
            "last_scan_age_hours": self.last_scan_age_hours,
        }

    def add_pattern(self, pattern: LearnedPattern) -> bool:
        """Agrega un patrón manualmente.

        Returns:
            True si se agregó (no existía).
        """
        existing = {p.env_var for p in self._store.patterns}
        if pattern.env_var in existing:
            return False
        pattern.learned_at = time.time()
        self._store.patterns.append(pattern)
        self._save()
        return True

    def remove_pattern(self, env_var: str) -> bool:
        """Elimina un patrón por env_var.

        Returns:
            True si se eliminó.
        """
        before = len(self._store.patterns)
        self._store.patterns = [
            p for p in self._store.patterns if p.env_var != env_var
        ]
        if len(self._store.patterns) < before:
            self._save()
            return True
        return False

    def _extract_from_skill(self, skill_path: Path) -> List[LearnedPattern]:
        """Extrae patrones de un archivo SKILL.md."""
        content = skill_path.read_text(encoding="utf-8")
        parsed = parse_skill_md(content)
        meta = parsed.get("meta", {})
        skill_name = meta.get("name", skill_path.parent.name)

        patterns: List[LearnedPattern] = []

        # 1. Extraer de metadata.somer.secrets[]
        oc_meta = meta.get("metadata", {})
        if isinstance(oc_meta, dict):
            somer_meta = oc_meta.get("somer", {}) or oc_meta.get("openclaw", {})
            if isinstance(somer_meta, dict):
                secrets = somer_meta.get("secrets", [])
                if isinstance(secrets, list):
                    for secret in secrets:
                        if isinstance(secret, dict) and "key" in secret:
                            patterns.append(LearnedPattern(
                                env_var=secret["key"],
                                service=skill_name,
                                description=secret.get("description", ""),
                                kind=self._guess_kind(secret["key"]),
                                source_skill=skill_name,
                                learned_at=time.time(),
                                context_keywords=self._generate_keywords(
                                    skill_name, secret["key"],
                                ),
                            ))

        # 2. Extraer de metadata.somer.requires.env[]
        if isinstance(oc_meta, dict):
            somer_meta = oc_meta.get("somer", {}) or oc_meta.get("openclaw", {})
            if isinstance(somer_meta, dict):
                requires = somer_meta.get("requires", {})
                if isinstance(requires, dict):
                    env_vars = requires.get("env", [])
                    if isinstance(env_vars, list):
                        existing = {p.env_var for p in patterns}
                        for var in env_vars:
                            if var not in existing:
                                patterns.append(LearnedPattern(
                                    env_var=var,
                                    service=skill_name,
                                    description=f"Requerido por skill {skill_name}",
                                    kind=self._guess_kind(var),
                                    source_skill=skill_name,
                                    learned_at=time.time(),
                                    context_keywords=self._generate_keywords(
                                        skill_name, var,
                                    ),
                                ))

        # 3. Extraer de required_credentials[] (formato directo)
        req_creds = meta.get("required_credentials", [])
        if isinstance(req_creds, list):
            existing = {p.env_var for p in patterns}
            for var in req_creds:
                if var not in existing:
                    patterns.append(LearnedPattern(
                        env_var=var,
                        service=skill_name,
                        description=f"Requerido por skill {skill_name}",
                        kind=self._guess_kind(var),
                        source_skill=skill_name,
                        learned_at=time.time(),
                        context_keywords=self._generate_keywords(
                            skill_name, var,
                        ),
                    ))

        return patterns

    @staticmethod
    def _guess_kind(env_var: str) -> str:
        """Adivina el tipo de credencial por el nombre de la variable."""
        upper = env_var.upper()
        if "TOKEN" in upper:
            return "token"
        if "SECRET" in upper or "PASSWORD" in upper:
            return "secret"
        if "_ID" in upper or "_SID" in upper:
            return "id"
        if "_URL" in upper or "_URI" in upper:
            return "url"
        return "api_key"

    @staticmethod
    def _kind_to_keyword(kind: str) -> str:
        """Convierte kind a keyword regex para detección."""
        return {
            "api_key": "(?:api[\\s_-]*)?key",
            "token": "(?:api[\\s_-]*)?token",
            "secret": "(?:api[\\s_-]*)?secret",
            "id": "(?:board[\\s_-]*|database[\\s_-]*|project[\\s_-]*)?id",
            "url": "(?:url|uri|connection)",
        }.get(kind, "(?:key|token|secret)")

    @staticmethod
    def _generate_keywords(skill_name: str, env_var: str) -> List[str]:
        """Genera keywords de contexto para una variable."""
        # "trello" + "api key" → ["trello[\\s_-]*(?:api[\\s_-]*)?key"]
        service = skill_name.lower().replace("-", "[\\s_-]*")
        # Extraer el tipo del nombre de variable
        var_lower = env_var.lower()
        suffixes = []
        if "api_key" in var_lower or var_lower.endswith("_key"):
            suffixes.append("(?:api[\\s_-]*)?key")
        if "token" in var_lower:
            suffixes.append("(?:api[\\s_-]*)?token")
            suffixes.append("(?:oauth[\\s_-]*)?token")
        if "secret" in var_lower:
            suffixes.append("(?:api[\\s_-]*)?secret")
        if "password" in var_lower:
            suffixes.append("(?:app[\\s_-]*)?password")
        if "_id" in var_lower:
            # Extraer qué tipo de ID
            parts = var_lower.replace(skill_name.lower() + "_", "").replace("_id", "")
            if parts:
                id_type = parts.replace("_", "[\\s_-]*")
                suffixes.append(f"{id_type}[\\s_-]*id")
            suffixes.append("id")
        if "_url" in var_lower:
            suffixes.append("(?:url|uri|connection)")

        if not suffixes:
            suffixes = ["(?:key|token|secret)"]

        return [f"{service}[\\s_-]*{s}" for s in suffixes]
