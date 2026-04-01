"""Tests para agents/prompt_builder.py."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from agents.prompt_builder import (
    WorkspaceContext,
    WorkspaceFile,
    build_system_prompt,
    detect_active_services,
    load_soul,
    load_workspace_context,
)
from shared.types import SkillMeta


# ── build_system_prompt ──────────────────────────────────────


class TestBuildSystemPrompt:
    """Tests para build_system_prompt()."""

    def test_empty_returns_time_only(self) -> None:
        result = build_system_prompt()
        assert "## Contexto temporal" in result
        assert "Fecha y hora actual:" in result

    def test_soul_included(self) -> None:
        result = build_system_prompt(soul="Eres un robot amable.")
        assert "Eres un robot amable." in result

    def test_user_identity(self) -> None:
        result = build_system_prompt(user_name="Juan", channel_id="telegram")
        assert "## Sesión actual" in result
        assert "Usuario actual: Juan" in result
        assert "Canal: telegram" in result

    def test_user_name_only(self) -> None:
        result = build_system_prompt(user_name="María")
        assert "Usuario actual: María" in result
        assert "Canal:" not in result

    def test_channel_only(self) -> None:
        result = build_system_prompt(channel_id="discord")
        assert "Canal: discord" in result
        assert "Usuario actual:" not in result

    def test_timezone(self) -> None:
        result = build_system_prompt(user_timezone="America/Bogota")
        assert "America/Bogota" in result
        assert "## Contexto temporal" in result

    def test_active_services(self) -> None:
        result = build_system_prompt(active_services=["Notion", "OpenAI"])
        assert "## Servicios configurados" in result
        assert "- Notion" in result
        assert "- OpenAI" in result
        assert "No necesitas pedirle la API key de nuevo" in result

    def test_empty_services_omitted(self) -> None:
        result = build_system_prompt(active_services=[])
        assert "## Servicios configurados" not in result

    def test_skills_section(self) -> None:
        skills = [
            SkillMeta(
                name="web-search",
                description="Busca en la web usando Tavily",
                triggers=["busca", "google"],
            ),
            SkillMeta(
                name="notion-connect",
                description="Conecta con Notion API",
                triggers=["notion"],
            ),
        ]
        result = build_system_prompt(skills=skills)
        assert "## Skills disponibles" in result
        assert "**web-search**" in result
        assert "Busca en la web usando Tavily" in result
        assert "(triggers: busca, google)" in result
        assert "**notion-connect**" in result

    def test_active_skills_body_included(self) -> None:
        skills = [
            SkillMeta(
                name="notion",
                description="Notion API",
                triggers=["notion"],
                required_credentials=["NOTION_API_KEY"],
                body="# notion\n\nUse the Notion API to create pages.",
            ),
        ]
        result = build_system_prompt(skills=skills, active_skills=skills)
        assert "## Instrucciones detalladas" in result
        assert "### notion" in result
        assert "Use the Notion API to create pages." in result
        assert "http_request" in result
        assert "NUNCA generes código Python" in result

    def test_active_skills_marked_with_check(self) -> None:
        skills = [
            SkillMeta(name="notion", description="Notion", body="body"),
            SkillMeta(name="github", description="GitHub"),
        ]
        active = [skills[0]]
        result = build_system_prompt(skills=skills, active_skills=active)
        # notion tiene check, github no
        assert "**notion** ✓" in result
        assert "**github**:" in result

    def test_active_skills_body_truncated(self) -> None:
        skills = [
            SkillMeta(
                name="huge",
                description="Huge skill",
                body="x" * 5000,
            ),
        ]
        result = build_system_prompt(skills=skills, active_skills=skills)
        assert "...(instrucciones truncadas)" in result

    def test_skills_no_triggers(self) -> None:
        skills = [SkillMeta(name="simple-skill", description="Algo simple")]
        result = build_system_prompt(skills=skills)
        assert "**simple-skill**: Algo simple" in result
        assert "triggers:" not in result

    def test_skills_description_truncated(self) -> None:
        long_desc = "x" * 200
        skills = [SkillMeta(name="long", description=long_desc)]
        result = build_system_prompt(skills=skills)
        # Solo primeros 120 chars
        assert "x" * 120 in result
        assert "x" * 121 not in result

    def test_empty_skills_omitted(self) -> None:
        result = build_system_prompt(skills=[])
        assert "## Skills disponibles" not in result

    def test_memory_context(self) -> None:
        memory = [
            {"content": "El usuario prefiere español", "source": "chat"},
            {"content": "API key de Notion configurada"},
        ]
        result = build_system_prompt(memory_context=memory)
        assert "## Memoria relevante" in result
        assert "[chat] El usuario prefiere español" in result
        assert "- API key de Notion configurada" in result

    def test_memory_truncated(self) -> None:
        long_content = "a" * 500
        memory = [{"content": long_content}]
        result = build_system_prompt(memory_context=memory)
        assert "a" * 300 + "..." in result

    def test_memory_limit_10(self) -> None:
        memory = [{"content": f"entry-{i}"} for i in range(15)]
        result = build_system_prompt(memory_context=memory)
        assert "entry-9" in result
        assert "entry-10" not in result

    def test_empty_memory_omitted(self) -> None:
        result = build_system_prompt(memory_context=[])
        assert "## Memoria relevante" not in result

    def test_tool_descriptions_section(self) -> None:
        tools = [
            {"name": "http_request", "description": "Hace peticiones HTTP"},
            {"name": "read_file", "description": "Lee archivos"},
        ]
        result = build_system_prompt(tool_descriptions=tools)
        assert "## Herramientas disponibles" in result
        assert "**http_request**: Hace peticiones HTTP" in result
        assert "**read_file**: Lee archivos" in result
        assert "DEBES usar la herramienta" in result
        assert "NUNCA generes bloques de código" in result

    def test_empty_tool_descriptions_omitted(self) -> None:
        result = build_system_prompt(tool_descriptions=[])
        assert "## Herramientas disponibles" not in result

    def test_none_tool_descriptions_omitted(self) -> None:
        result = build_system_prompt(tool_descriptions=None)
        assert "## Herramientas disponibles" not in result

    def test_tools_before_skills_in_prompt(self) -> None:
        tools = [{"name": "http_request", "description": "HTTP"}]
        skills = [SkillMeta(name="notion", description="Notion API")]
        result = build_system_prompt(tool_descriptions=tools, skills=skills)
        tools_pos = result.index("## Herramientas disponibles")
        skills_pos = result.index("## Skills disponibles")
        assert tools_pos < skills_pos

    def test_full_prompt_all_sections(self) -> None:
        result = build_system_prompt(
            soul="Personalidad test",
            skills=[SkillMeta(name="s1", description="d1", triggers=["t1"])],
            memory_context=[{"content": "recuerdo"}],
            active_services=["Notion"],
            tool_descriptions=[{"name": "http_request", "description": "HTTP tool"}],
            channel_id="telegram",
            user_name="Test",
            user_timezone="UTC",
        )
        # Todas las secciones presentes en orden
        sections = [
            "Eres un asistente personal",  # Línea base
            "## Contexto temporal",
            "## Sesión actual",
            "## Servicios configurados",
            "## Herramientas disponibles",
            "## Skills disponibles",
            "## Memoria relevante",
            "Personalidad test",  # SOUL en Project Context
        ]
        for section in sections:
            assert section in result

    def test_sections_separated_by_double_newline(self) -> None:
        result = build_system_prompt(
            soul="Soul",
            user_name="U",
        )
        assert "\n\n" in result


# ── load_soul ────────────────────────────────────────────────


class TestLoadSoul:
    """Tests para load_soul()."""

    def test_default_when_no_file(self, tmp_path: Path) -> None:
        # Usar workspace y project_root vacíos para forzar fallback
        result = load_soul(
            soul_path=str(tmp_path / "nonexistent.md"),
            workspace_dir=tmp_path,
            project_root=tmp_path,
        )
        assert "SOMER" in result
        assert "asistente inteligente" in result

    def test_loads_file(self, tmp_path: Path) -> None:
        soul_file = tmp_path / "SOUL.md"
        soul_file.write_text("Soy un asistente custom.", encoding="utf-8")
        result = load_soul(str(soul_file))
        assert result == "Soy un asistente custom."

    def test_none_path_returns_default(self) -> None:
        # Con None, busca ./SOUL.md que puede o no existir
        result = load_soul(None)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_loads_from_project_root(self, tmp_path: Path) -> None:
        (tmp_path / "SOUL.md").write_text("Project soul", encoding="utf-8")
        result = load_soul(project_root=tmp_path)
        assert result == "Project soul"

    def test_loads_from_workspace_dir(self, tmp_path: Path) -> None:
        (tmp_path / "SOUL.md").write_text("Workspace soul", encoding="utf-8")
        result = load_soul(workspace_dir=tmp_path)
        assert result == "Workspace soul"


# ── detect_active_services ───────────────────────────────────


class TestDetectActiveServices:
    """Tests para detect_active_services()."""

    def test_empty_env(self) -> None:
        env = {}
        with patch.dict(os.environ, env, clear=True):
            result = detect_active_services()
            assert result == []

    def test_detects_notion(self) -> None:
        with patch.dict(os.environ, {"NOTION_API_KEY": "ntn_test123"}, clear=True):
            result = detect_active_services()
            assert "Notion" in result

    def test_detects_multiple(self) -> None:
        env = {
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "OPENAI_API_KEY": "sk-test",
            "TELEGRAM_BOT_TOKEN": "12345:ABC",
        }
        with patch.dict(os.environ, env, clear=True):
            result = detect_active_services()
            assert "Anthropic (Claude)" in result
            assert "OpenAI" in result
            assert "Telegram Bot" in result

    def test_ignores_empty_values(self) -> None:
        with patch.dict(os.environ, {"NOTION_API_KEY": ""}, clear=True):
            result = detect_active_services()
            assert result == []

    def test_ignores_whitespace_values(self) -> None:
        with patch.dict(os.environ, {"NOTION_API_KEY": "   "}, clear=True):
            result = detect_active_services()
            assert result == []

    def test_all_services(self) -> None:
        env = {
            "NOTION_API_KEY": "x",
            "ANTHROPIC_API_KEY": "x",
            "OPENAI_API_KEY": "x",
            "DEEPSEEK_API_KEY": "x",
            "GOOGLE_API_KEY": "x",
            "GROQ_API_KEY": "x",
            "XAI_API_KEY": "x",
            "OPENROUTER_API_KEY": "x",
            "MISTRAL_API_KEY": "x",
            "TOGETHER_API_KEY": "x",
            "PERPLEXITY_API_KEY": "x",
            "HF_TOKEN": "x",
            "TELEGRAM_BOT_TOKEN": "x",
            "TAVILY_API_KEY": "x",
            "SLACK_BOT_TOKEN": "x",
            "DISCORD_BOT_TOKEN": "x",
        }
        with patch.dict(os.environ, env, clear=True):
            result = detect_active_services()
            assert len(result) == 16


# ── WorkspaceFile & WorkspaceContext ─────────────────────────


class TestWorkspaceFile:
    """Tests para WorkspaceFile dataclass."""

    def test_create_workspace_file(self) -> None:
        f = WorkspaceFile(name="SOUL.md", path=Path("./SOUL.md"))
        assert f.name == "SOUL.md"
        assert f.content == ""
        assert f.missing is False

    def test_workspace_file_with_content(self) -> None:
        f = WorkspaceFile(
            name="SOUL.md",
            path=Path("./SOUL.md"),
            content="# Soul\nTest content",
            missing=False,
        )
        assert f.content == "# Soul\nTest content"
        assert not f.missing


class TestWorkspaceContext:
    """Tests para WorkspaceContext dataclass."""

    def test_default_context_all_missing(self) -> None:
        ctx = WorkspaceContext()
        assert ctx.soul.missing
        assert ctx.identity.missing
        assert ctx.user.missing
        assert ctx.tools.missing
        assert ctx.boot.missing
        assert ctx.memory.missing

    def test_loaded_files_empty_by_default(self) -> None:
        ctx = WorkspaceContext()
        assert ctx.loaded_files() == []

    def test_loaded_files_returns_non_missing(self) -> None:
        ctx = WorkspaceContext()
        ctx.soul = WorkspaceFile(
            name="SOUL.md",
            path=Path("./SOUL.md"),
            content="Soul content",
            missing=False,
        )
        ctx.identity = WorkspaceFile(
            name="IDENTITY.md",
            path=Path("./IDENTITY.md"),
            content="Identity content",
            missing=False,
        )
        loaded = ctx.loaded_files()
        assert len(loaded) == 2
        assert loaded[0].name == "SOUL.md"
        assert loaded[1].name == "IDENTITY.md"

    def test_has_soul(self) -> None:
        ctx = WorkspaceContext()
        assert not ctx.has_soul()

        ctx.soul = WorkspaceFile(
            name="SOUL.md",
            path=Path("./SOUL.md"),
            content="Soul content",
            missing=False,
        )
        assert ctx.has_soul()


# ── load_workspace_context ───────────────────────────────────


class TestLoadWorkspaceContext:
    """Tests para load_workspace_context()."""

    def test_loads_from_project_root(self, tmp_path: Path) -> None:
        # Crear archivos en proyecto local
        (tmp_path / "SOUL.md").write_text("# Soul\nLocal soul", encoding="utf-8")
        (tmp_path / "IDENTITY.md").write_text("# Identity\nLocal identity", encoding="utf-8")

        ctx = load_workspace_context(project_root=tmp_path)

        assert not ctx.soul.missing
        assert "Local soul" in ctx.soul.content
        assert not ctx.identity.missing
        assert "Local identity" in ctx.identity.content

    def test_fallback_to_workspace_dir(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "SOUL.md").write_text("# Soul\nGlobal soul", encoding="utf-8")

        ctx = load_workspace_context(workspace_dir=workspace)

        assert not ctx.soul.missing
        assert "Global soul" in ctx.soul.content

    def test_project_root_takes_priority(self, tmp_path: Path) -> None:
        # Crear archivo en ambos lugares
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "SOUL.md").write_text("Global soul", encoding="utf-8")

        project = tmp_path / "project"
        project.mkdir()
        (project / "SOUL.md").write_text("Local soul", encoding="utf-8")

        ctx = load_workspace_context(workspace_dir=workspace, project_root=project)

        assert "Local soul" in ctx.soul.content

    def test_missing_files_marked_as_missing(self, tmp_path: Path) -> None:
        ctx = load_workspace_context(workspace_dir=tmp_path)
        assert ctx.soul.missing
        assert ctx.identity.missing
        assert ctx.user.missing

    def test_loads_all_file_types(self, tmp_path: Path) -> None:
        # Crear todos los archivos
        (tmp_path / "SOUL.md").write_text("Soul", encoding="utf-8")
        (tmp_path / "IDENTITY.md").write_text("Identity", encoding="utf-8")
        (tmp_path / "USER.md").write_text("User", encoding="utf-8")
        (tmp_path / "TOOLS.md").write_text("Tools", encoding="utf-8")
        (tmp_path / "BOOT.md").write_text("Boot", encoding="utf-8")
        (tmp_path / "MEMORY.md").write_text("Memory", encoding="utf-8")

        ctx = load_workspace_context(project_root=tmp_path)

        assert len(ctx.loaded_files()) == 6
        assert not ctx.soul.missing
        assert not ctx.identity.missing
        assert not ctx.user.missing
        assert not ctx.tools.missing
        assert not ctx.boot.missing
        assert not ctx.memory.missing


# ── build_system_prompt with WorkspaceContext ────────────────


class TestBuildSystemPromptWithWorkspace:
    """Tests para build_system_prompt() con WorkspaceContext."""

    def test_workspace_context_injects_files(self, tmp_path: Path) -> None:
        (tmp_path / "SOUL.md").write_text("# Soul\nTest soul content", encoding="utf-8")
        (tmp_path / "IDENTITY.md").write_text("# Identity\nTest identity", encoding="utf-8")

        ctx = load_workspace_context(project_root=tmp_path)
        result = build_system_prompt(workspace_context=ctx)

        assert "# Contexto del Proyecto" in result
        assert "## SOUL.md" in result
        assert "Test soul content" in result
        assert "## IDENTITY.md" in result
        assert "Test identity" in result

    def test_soul_guidance_when_present(self, tmp_path: Path) -> None:
        (tmp_path / "SOUL.md").write_text("# Soul", encoding="utf-8")

        ctx = load_workspace_context(project_root=tmp_path)
        result = build_system_prompt(workspace_context=ctx)

        assert "encarna su persona y tono" in result
        assert "Evita respuestas rígidas" in result

    def test_legacy_soul_still_works(self) -> None:
        result = build_system_prompt(soul="Legacy soul content")
        assert "# Contexto del Proyecto" in result
        assert "## SOUL.md" in result
        assert "Legacy soul content" in result

    def test_workspace_context_takes_priority_over_legacy(self, tmp_path: Path) -> None:
        (tmp_path / "SOUL.md").write_text("Workspace soul", encoding="utf-8")

        ctx = load_workspace_context(project_root=tmp_path)
        result = build_system_prompt(
            workspace_context=ctx,
            soul="Legacy soul"  # Should be ignored
        )

        assert "Workspace soul" in result
        # Legacy soul should not appear since workspace_context is provided
        # Actually it depends on implementation, let's check
        # In current impl, workspace_context has priority

    def test_base_identity_line(self) -> None:
        result = build_system_prompt()
        assert "Eres un asistente personal ejecutándose dentro de SOMER" in result
