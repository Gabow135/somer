"""Tests para el CLI de SOMER 2.0.

Cubre todos los comandos registrados: version, info, config, gateway,
agent, channels, doctor, plugins, cron, secrets, memory, skills.
"""

from __future__ import annotations

from typer.testing import CliRunner

from cli.app import app
from shared.constants import VERSION

runner = CliRunner()


class TestCLI:
    """Tests básicos del CLI."""

    def test_version(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert VERSION in result.output

    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "SOMER" in result.output

    def test_info(self) -> None:
        result = runner.invoke(app, ["info"])
        assert result.exit_code == 0
        assert VERSION in result.output

    def test_info_json(self) -> None:
        result = runner.invoke(app, ["info", "--json"])
        assert result.exit_code == 0
        assert "version" in result.output


class TestConfigCLI:
    """Tests del módulo config."""

    def test_config_path(self) -> None:
        result = runner.invoke(app, ["config", "path"])
        assert result.exit_code == 0
        assert ".somer" in result.output

    def test_config_show(self) -> None:
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0

    def test_config_show_json(self) -> None:
        result = runner.invoke(app, ["config", "show", "--json"])
        assert result.exit_code == 0

    def test_config_show_section(self) -> None:
        result = runner.invoke(app, ["config", "show", "--section", "gateway"])
        assert result.exit_code == 0

    def test_config_diff(self) -> None:
        result = runner.invoke(app, ["config", "diff"])
        assert result.exit_code == 0

    def test_config_help_section_gateway(self) -> None:
        result = runner.invoke(app, ["config", "help-section", "gateway"])
        assert result.exit_code == 0
        assert "gateway" in result.output.lower()

    def test_config_help_section_invalid(self) -> None:
        result = runner.invoke(app, ["config", "help-section", "nonexistent"])
        assert result.exit_code == 1

    def test_config_get_default_model(self) -> None:
        result = runner.invoke(app, ["config", "get", "default_model"])
        assert result.exit_code == 0

    def test_config_get_nonexistent(self) -> None:
        result = runner.invoke(app, ["config", "get", "nonexistent.key"])
        assert result.exit_code == 1

    def test_config_no_args_shows_help(self) -> None:
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0

    def test_config_validate(self) -> None:
        result = runner.invoke(app, ["config", "validate"])
        # Puede ser 0 o 1 dependiendo de la config, lo importante es que no crashea
        assert result.exit_code in (0, 1)


class TestGatewayCLI:
    """Tests del módulo gateway."""

    def test_gateway_status(self) -> None:
        result = runner.invoke(app, ["gateway", "status"])
        assert result.exit_code == 0

    def test_gateway_status_json(self) -> None:
        result = runner.invoke(app, ["gateway", "status", "--json"])
        assert result.exit_code == 0
        assert "running" in result.output

    def test_gateway_no_args_shows_help(self) -> None:
        result = runner.invoke(app, ["gateway"])
        assert result.exit_code == 0


class TestAgentCLI:
    """Tests del módulo agent."""

    def test_agent_no_args_shows_help(self) -> None:
        result = runner.invoke(app, ["agent"])
        assert result.exit_code == 0

    def test_agent_status(self) -> None:
        result = runner.invoke(app, ["agent", "status"])
        assert result.exit_code == 0

    def test_agent_status_json(self) -> None:
        result = runner.invoke(app, ["agent", "status", "--json"])
        assert result.exit_code == 0
        assert "default_model" in result.output

    def test_agent_list(self) -> None:
        result = runner.invoke(app, ["agent", "list"])
        assert result.exit_code == 0
        assert "default" in result.output

    def test_agent_config(self) -> None:
        result = runner.invoke(app, ["agent", "config"])
        assert result.exit_code == 0


class TestChannelsCLI:
    """Tests del módulo channels."""

    def test_channels_list(self) -> None:
        result = runner.invoke(app, ["channels", "list"])
        assert result.exit_code == 0

    def test_channels_list_json(self) -> None:
        result = runner.invoke(app, ["channels", "list", "--json"])
        assert result.exit_code == 0

    def test_channels_status(self) -> None:
        result = runner.invoke(app, ["channels", "status"])
        assert result.exit_code == 0

    def test_channels_no_args_shows_help(self) -> None:
        result = runner.invoke(app, ["channels"])
        assert result.exit_code == 0


class TestDoctorCLI:
    """Tests del módulo doctor."""

    def test_doctor_check(self) -> None:
        result = runner.invoke(app, ["doctor", "check"])
        assert result.exit_code == 0
        assert "SOMER Doctor" in result.output

    def test_doctor_check_json(self) -> None:
        result = runner.invoke(app, ["doctor", "check", "--json"])
        assert result.exit_code == 0
        assert "passed" in result.output

    def test_doctor_check_category_system(self) -> None:
        result = runner.invoke(app, ["doctor", "check", "--category", "system"])
        assert result.exit_code == 0

    def test_doctor_check_category_config(self) -> None:
        result = runner.invoke(app, ["doctor", "check", "--category", "config"])
        assert result.exit_code == 0

    def test_doctor_check_category_deps(self) -> None:
        result = runner.invoke(app, ["doctor", "check", "--category", "deps"])
        assert result.exit_code == 0

    def test_doctor_check_invalid_category(self) -> None:
        result = runner.invoke(app, ["doctor", "check", "--category", "nonexistent"])
        assert result.exit_code == 1

    def test_doctor_env(self) -> None:
        result = runner.invoke(app, ["doctor", "env"])
        assert result.exit_code == 0
        assert "Entorno" in result.output

    def test_doctor_providers(self) -> None:
        result = runner.invoke(app, ["doctor", "providers"])
        assert result.exit_code == 0

    def test_doctor_no_args_shows_help(self) -> None:
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0


class TestPluginsCLI:
    """Tests del módulo plugins."""

    def test_plugins_no_args_shows_help(self) -> None:
        result = runner.invoke(app, ["plugins"])
        assert result.exit_code == 0

    def test_plugins_list(self) -> None:
        result = runner.invoke(app, ["plugins", "list"])
        assert result.exit_code == 0

    def test_plugins_list_json(self) -> None:
        result = runner.invoke(app, ["plugins", "list", "--json"])
        assert result.exit_code == 0


class TestCronCLI:
    """Tests del módulo cron."""

    def test_cron_no_args_shows_help(self) -> None:
        result = runner.invoke(app, ["cron"])
        assert result.exit_code == 0

    def test_cron_list_requires_gateway(self) -> None:
        """cron list requiere gateway corriendo — exit 1 si no está."""
        result = runner.invoke(app, ["cron", "list"])
        assert result.exit_code == 1

    def test_cron_list_json_requires_gateway(self) -> None:
        result = runner.invoke(app, ["cron", "list", "--json"])
        assert result.exit_code == 1

    def test_cron_status_requires_gateway(self) -> None:
        result = runner.invoke(app, ["cron", "status"])
        assert result.exit_code == 1

    def test_cron_status_json_requires_gateway(self) -> None:
        result = runner.invoke(app, ["cron", "status", "--json"])
        assert result.exit_code == 1


class TestSecretsCLI:
    """Tests del módulo secrets."""

    def test_secrets_no_args_shows_help(self) -> None:
        result = runner.invoke(app, ["secrets"])
        assert result.exit_code == 0

    def test_secrets_list(self) -> None:
        result = runner.invoke(app, ["secrets", "list"])
        assert result.exit_code == 0

    def test_secrets_list_json(self) -> None:
        result = runner.invoke(app, ["secrets", "list", "--json"])
        assert result.exit_code == 0


class TestMemoryCLI:
    """Tests del módulo memory."""

    def test_memory_no_args_shows_help(self) -> None:
        result = runner.invoke(app, ["memory"])
        assert result.exit_code == 0

    def test_memory_sources(self) -> None:
        result = runner.invoke(app, ["memory", "sources"])
        assert result.exit_code == 0
        assert "Fuentes" in result.output

    def test_memory_stats(self) -> None:
        result = runner.invoke(app, ["memory", "stats"])
        assert result.exit_code == 0


class TestSkillsCLI:
    """Tests del módulo skills."""

    def test_skills_no_args_shows_help(self) -> None:
        result = runner.invoke(app, ["skills"])
        assert result.exit_code == 0

    def test_skills_list(self) -> None:
        result = runner.invoke(app, ["skills", "list"])
        assert result.exit_code == 0

    def test_skills_list_json(self) -> None:
        result = runner.invoke(app, ["skills", "list", "--json"])
        assert result.exit_code == 0

    def test_skills_check(self) -> None:
        result = runner.invoke(app, ["skills", "check"])
        assert result.exit_code == 0

    def test_skills_check_json(self) -> None:
        result = runner.invoke(app, ["skills", "check", "--json"])
        assert result.exit_code == 0

    def test_skills_search(self) -> None:
        result = runner.invoke(app, ["skills", "search", "test"])
        assert result.exit_code == 0

    def test_skills_info_nonexistent(self) -> None:
        result = runner.invoke(app, ["skills", "info", "nonexistent_skill_xyz"])
        assert result.exit_code == 1
