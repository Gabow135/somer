"""Tests para el sistema de skills."""

from __future__ import annotations

from pathlib import Path

import pytest

from skills.loader import discover_skills, load_skill_file, parse_skill_md
from skills.registry import SkillRegistry
from skills.validator import validate_skill
from shared.errors import SkillValidationError
from shared.types import SkillMeta


class TestSkillLoader:
    """Tests del loader de SKILL.md."""

    def test_parse_frontmatter(self) -> None:
        content = """---
name: test-skill
description: A test skill
version: 1.0.0
triggers:
  - test
  - prueba
tags:
  - testing
---

# Test Skill

Body content here.
"""
        result = parse_skill_md(content)
        assert result["meta"]["name"] == "test-skill"
        assert result["meta"]["description"] == "A test skill"
        assert "test" in result["meta"]["triggers"]
        assert "Body content here." in result["body"]

    def test_parse_no_frontmatter(self) -> None:
        content = "# Just a title\n\nSome content"
        result = parse_skill_md(content)
        assert result["meta"] == {}
        assert "Just a title" in result["body"]

    def test_load_real_skill(self) -> None:
        path = Path("skills/notion/SKILL.md")
        if path.exists():
            meta = load_skill_file(path)
            assert meta.name == "notion"
            assert len(meta.triggers) > 0
            assert "NOTION_API_KEY" in meta.required_credentials

    def test_load_nonexistent(self) -> None:
        with pytest.raises(SkillValidationError):
            load_skill_file(Path("/nonexistent/SKILL.md"))

    def test_discover_skills(self) -> None:
        found = discover_skills(["skills"])
        # Al menos notion y github
        names = [p.parent.name for p in found]
        if Path("skills/notion/SKILL.md").exists():
            assert "notion" in names


class TestSkillRegistry:
    """Tests del registry de skills."""

    def test_register(self) -> None:
        registry = SkillRegistry()
        skill = SkillMeta(
            name="test", description="Test", triggers=["test", "prueba"]
        )
        registry.register(skill)
        assert registry.skill_count == 1

    def test_match_trigger(self) -> None:
        registry = SkillRegistry()
        skill = SkillMeta(
            name="notion", description="Notion", triggers=["notion", "buscar en notion"]
        )
        registry.register(skill)
        match = registry.match_trigger("quiero buscar en notion algo")
        assert match is not None
        assert match.name == "notion"

    def test_no_match(self) -> None:
        registry = SkillRegistry()
        skill = SkillMeta(name="notion", triggers=["notion"])
        registry.register(skill)
        assert registry.match_trigger("hola mundo") is None

    def test_search_by_tag(self) -> None:
        registry = SkillRegistry()
        s1 = SkillMeta(name="s1", tags=["dev", "api"])
        s2 = SkillMeta(name="s2", tags=["dev", "db"])
        s3 = SkillMeta(name="s3", tags=["design"])
        registry.register(s1)
        registry.register(s2)
        registry.register(s3)
        devs = registry.search_by_tag("dev")
        assert len(devs) == 2

    def test_disabled_skill_not_matched(self) -> None:
        registry = SkillRegistry()
        skill = SkillMeta(
            name="disabled", triggers=["disabled"], enabled=False
        )
        registry.register(skill)
        assert registry.match_trigger("disabled skill") is None

    def test_list_enabled(self) -> None:
        registry = SkillRegistry()
        s1 = SkillMeta(name="s1", enabled=True)
        s2 = SkillMeta(name="s2", enabled=False)
        registry.register(s1)
        registry.register(s2)
        enabled = registry.list_enabled()
        assert len(enabled) == 1

    def test_unregister(self) -> None:
        registry = SkillRegistry()
        skill = SkillMeta(name="bye", triggers=["bye"])
        registry.register(skill)
        registry.unregister("bye")
        assert registry.skill_count == 0


class TestSkillValidator:
    """Tests del validador."""

    def test_valid_skill(self) -> None:
        skill = SkillMeta(
            name="good",
            description="Good skill",
            triggers=["good"],
            tools=[{"name": "good_tool"}],
        )
        warnings = validate_skill(skill)
        assert len(warnings) == 0

    def test_missing_description(self) -> None:
        skill = SkillMeta(name="nodesc", triggers=["x"], tools=[{"name": "t"}])
        warnings = validate_skill(skill)
        assert any("descripción" in w for w in warnings)

    def test_missing_name(self) -> None:
        skill = SkillMeta(name="")
        with pytest.raises(SkillValidationError):
            validate_skill(skill)
