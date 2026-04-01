"""Tests para el sistema de secretos.

Tests para: refs, store, resolve, collectors, validation, rotation, apply.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict

import pytest

from secrets.refs import (
    SecretExpectedValue,
    SecretRef,
    SecretResolveCache,
    SecretSource,
    is_expected_resolved_value,
    is_valid_exec_ref_id,
    is_valid_provider_alias,
    resolve_refs_batch,
)
from secrets.store import CredentialStore
from shared.errors import (
    SecretDecryptionError,
    SecretNotFoundError,
    SecretRefResolutionError,
)


# ═══════════════════════════════════════════════════════════════
# SecretRef — tests originales + extensiones
# ═══════════════════════════════════════════════════════════════

class TestSecretRef:
    """Tests de SecretRef."""

    def test_resolve_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_SECRET", "my-value")
        ref = SecretRef.from_env("TEST_SECRET")
        assert ref.resolve() == "my-value"

    def test_resolve_env_missing(self) -> None:
        ref = SecretRef.from_env("NONEXISTENT_VAR_12345")
        with pytest.raises(SecretRefResolutionError):
            ref.resolve()

    def test_resolve_file(self, tmp_path: Path) -> None:
        secret_file = tmp_path / "secret.txt"
        secret_file.write_text("file-secret-value")
        ref = SecretRef.from_file(str(secret_file))
        assert ref.resolve() == "file-secret-value"

    def test_resolve_file_missing(self) -> None:
        ref = SecretRef.from_file("/nonexistent/path/secret.txt")
        with pytest.raises(SecretRefResolutionError):
            ref.resolve()

    def test_resolve_exec(self) -> None:
        ref = SecretRef.from_exec("echo test-exec-value")
        assert ref.resolve() == "test-exec-value"

    def test_resolve_exec_fail(self) -> None:
        ref = SecretRef.from_exec("false")
        with pytest.raises(SecretRefResolutionError):
            ref.resolve()

    def test_literal(self) -> None:
        ref = SecretRef.literal("literal-value")
        assert ref.resolve() == "literal-value"

    def test_source_types(self) -> None:
        assert SecretRef.from_env("X").source == SecretSource.ENV
        assert SecretRef.from_file("/x").source == SecretSource.FILE
        assert SecretRef.from_exec("x").source == SecretSource.EXEC
        assert SecretRef.literal("x").source == SecretSource.LITERAL

    # ── Nuevos tests: keychain source ───────────────────────

    def test_keychain_source_type(self) -> None:
        ref = SecretRef.from_keychain("my-service")
        assert ref.source == SecretSource.KEYCHAIN
        assert ref.key == "my-service"
        assert ref.provider == "keychain"

    # ── Nuevos tests: ref_key ───────────────────────────────

    def test_ref_key_format(self) -> None:
        ref = SecretRef.from_env("MY_KEY")
        assert ref.ref_key() == "env:default:MY_KEY"

    def test_ref_key_with_provider(self) -> None:
        ref = SecretRef(source=SecretSource.EXEC, key="get-secret", provider="vault")
        assert ref.ref_key() == "exec:vault:get-secret"

    # ── Nuevos tests: parse_ref_string ──────────────────────

    def test_parse_ref_string_env_dollar(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_API_KEY", "sk-test-123")
        ref = SecretRef.parse_ref_string("$MY_API_KEY")
        assert ref is not None
        assert ref.source == SecretSource.ENV
        assert ref.key == "MY_API_KEY"
        assert ref.resolve() == "sk-test-123"

    def test_parse_ref_string_env_full(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_KEY", "sk-abc")
        ref = SecretRef.parse_ref_string("env:default:OPENAI_KEY")
        assert ref is not None
        assert ref.source == SecretSource.ENV
        assert ref.provider == "default"
        assert ref.resolve() == "sk-abc"

    def test_parse_ref_string_file(self, tmp_path: Path) -> None:
        secret_file = tmp_path / "key.txt"
        secret_file.write_text("file-value")
        ref = SecretRef.parse_ref_string(f"file:{secret_file}")
        assert ref is not None
        assert ref.source == SecretSource.FILE

    def test_parse_ref_string_exec(self) -> None:
        ref = SecretRef.parse_ref_string("exec:echo hello")
        assert ref is not None
        assert ref.source == SecretSource.EXEC

    def test_parse_ref_string_keychain(self) -> None:
        ref = SecretRef.parse_ref_string("keychain:my-service")
        assert ref is not None
        assert ref.source == SecretSource.KEYCHAIN
        assert ref.key == "my-service"

    def test_parse_ref_string_literal(self) -> None:
        ref = SecretRef.parse_ref_string("literal:my-value")
        assert ref is not None
        assert ref.source == SecretSource.LITERAL
        assert ref.resolve() == "my-value"

    def test_parse_ref_string_none_for_empty(self) -> None:
        assert SecretRef.parse_ref_string("") is None
        assert SecretRef.parse_ref_string("   ") is None

    def test_parse_ref_string_none_for_non_ref(self) -> None:
        assert SecretRef.parse_ref_string("just-a-plain-string") is None

    # ── Nuevos tests: resolución asíncrona ──────────────────

    async def test_aresolve_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ASYNC_TEST", "async-value")
        ref = SecretRef.from_env("ASYNC_TEST")
        assert await ref.aresolve() == "async-value"

    async def test_aresolve_literal(self) -> None:
        ref = SecretRef.literal("async-literal")
        assert await ref.aresolve() == "async-literal"

    async def test_aresolve_exec(self) -> None:
        ref = SecretRef.from_exec("echo async-exec")
        assert await ref.aresolve() == "async-exec"

    async def test_aresolve_file(self, tmp_path: Path) -> None:
        f = tmp_path / "async_secret.txt"
        f.write_text("async-file-value")
        ref = SecretRef.from_file(str(f))
        assert await ref.aresolve() == "async-file-value"


# ═══════════════════════════════════════════════════════════════
# SecretResolveCache — tests
# ═══════════════════════════════════════════════════════════════

class TestSecretResolveCache:
    """Tests del caché de resolución."""

    def test_put_and_get(self) -> None:
        cache = SecretResolveCache()
        ref = SecretRef.from_env("MY_KEY")
        cache.put(ref, "the-value")
        assert cache.has(ref)
        assert cache.get(ref) == "the-value"

    def test_get_missing(self) -> None:
        cache = SecretResolveCache()
        ref = SecretRef.from_env("MISSING")
        assert not cache.has(ref)
        assert cache.get(ref) is None

    def test_clear(self) -> None:
        cache = SecretResolveCache()
        ref = SecretRef.literal("x")
        cache.put(ref, "val")
        assert cache.has(ref)
        cache.clear()
        assert not cache.has(ref)


# ═══════════════════════════════════════════════════════════════
# resolve_refs_batch — tests
# ═══════════════════════════════════════════════════════════════

class TestResolveRefsBatch:
    """Tests de resolución en lote."""

    async def test_batch_resolve_empty(self) -> None:
        result = await resolve_refs_batch([])
        assert result == {}

    async def test_batch_resolve_literals(self) -> None:
        refs = [
            SecretRef.literal("val-a"),
            SecretRef.literal("val-b"),
        ]
        result = await resolve_refs_batch(refs)
        assert len(result) == 2
        assert result[refs[0].ref_key()] == "val-a"
        assert result[refs[1].ref_key()] == "val-b"

    async def test_batch_resolve_with_cache(self) -> None:
        cache = SecretResolveCache()
        ref = SecretRef.literal("cached-val")
        cache.put(ref, "cached-val")

        result = await resolve_refs_batch([ref], cache=cache)
        assert result[ref.ref_key()] == "cached-val"

    async def test_batch_resolve_deduplication(self) -> None:
        refs = [
            SecretRef.literal("dup-val"),
            SecretRef.literal("dup-val"),  # Misma referencia
        ]
        result = await resolve_refs_batch(refs)
        # Solo debe haber una entrada (deduplicada por ref_key)
        assert len(result) == 1

    async def test_batch_resolve_mixed_sources(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("BATCH_ENV", "env-value")
        f = tmp_path / "batch.txt"
        f.write_text("file-value")

        refs = [
            SecretRef.from_env("BATCH_ENV"),
            SecretRef.from_file(str(f)),
            SecretRef.literal("lit-val"),
        ]
        result = await resolve_refs_batch(refs)
        assert len(result) == 3
        assert result[refs[0].ref_key()] == "env-value"
        assert result[refs[1].ref_key()] == "file-value"
        assert result[refs[2].ref_key()] == "lit-val"


# ═══════════════════════════════════════════════════════════════
# Validation helpers — tests
# ═══════════════════════════════════════════════════════════════

class TestValidationHelpers:
    """Tests de funciones de validación de refs."""

    def test_valid_exec_ref_id(self) -> None:
        assert is_valid_exec_ref_id("vault/openai/api-key")
        assert is_valid_exec_ref_id("simple-id")
        assert is_valid_exec_ref_id("my.id")

    def test_invalid_exec_ref_id(self) -> None:
        assert not is_valid_exec_ref_id("")
        assert not is_valid_exec_ref_id("../traversal")
        assert not is_valid_exec_ref_id("path/../bad")

    def test_valid_provider_alias(self) -> None:
        assert is_valid_provider_alias("default")
        assert is_valid_provider_alias("my-vault")
        assert is_valid_provider_alias("env_store")

    def test_invalid_provider_alias(self) -> None:
        assert not is_valid_provider_alias("")
        assert not is_valid_provider_alias("123start")
        assert not is_valid_provider_alias("UPPER")

    def test_is_expected_resolved_value_string(self) -> None:
        assert is_expected_resolved_value("hello", SecretExpectedValue.STRING)
        assert not is_expected_resolved_value("", SecretExpectedValue.STRING)
        assert not is_expected_resolved_value("   ", SecretExpectedValue.STRING)
        assert not is_expected_resolved_value(123, SecretExpectedValue.STRING)

    def test_is_expected_resolved_value_string_or_object(self) -> None:
        assert is_expected_resolved_value("hello", SecretExpectedValue.STRING_OR_OBJECT)
        assert is_expected_resolved_value({"k": "v"}, SecretExpectedValue.STRING_OR_OBJECT)
        assert not is_expected_resolved_value({}, SecretExpectedValue.STRING_OR_OBJECT)
        assert not is_expected_resolved_value("", SecretExpectedValue.STRING_OR_OBJECT)


# ═══════════════════════════════════════════════════════════════
# CredentialStore — tests originales
# ═══════════════════════════════════════════════════════════════

class TestCredentialStore:
    """Tests del CredentialStore."""

    def test_store_and_retrieve(self, tmp_path: Path) -> None:
        store = CredentialStore(credentials_dir=tmp_path / "creds")
        store.store("test-service", {"api_key": "sk-test", "extra": "data"})

        result = store.retrieve("test-service")
        assert result["api_key"] == "sk-test"
        assert result["extra"] == "data"

    def test_retrieve_nonexistent(self, tmp_path: Path) -> None:
        store = CredentialStore(credentials_dir=tmp_path / "creds")
        with pytest.raises(SecretNotFoundError):
            store.retrieve("nonexistent")

    def test_delete(self, tmp_path: Path) -> None:
        store = CredentialStore(credentials_dir=tmp_path / "creds")
        store.store("delete-me", {"key": "value"})
        assert store.has("delete-me")
        assert store.delete("delete-me")
        assert not store.has("delete-me")

    def test_delete_nonexistent(self, tmp_path: Path) -> None:
        store = CredentialStore(credentials_dir=tmp_path / "creds")
        assert not store.delete("nonexistent")

    def test_list_services(self, tmp_path: Path) -> None:
        store = CredentialStore(credentials_dir=tmp_path / "creds")
        store.store("alpha", {"k": "v"})
        store.store("beta", {"k": "v"})
        services = store.list_services()
        assert "alpha" in services
        assert "beta" in services

    def test_has(self, tmp_path: Path) -> None:
        store = CredentialStore(credentials_dir=tmp_path / "creds")
        assert not store.has("nope")
        store.store("exists", {"k": "v"})
        assert store.has("exists")

    def test_file_permissions(self, tmp_path: Path) -> None:
        store = CredentialStore(credentials_dir=tmp_path / "creds")
        store.store("perm-test", {"k": "v"})
        # Verificar que los archivos tienen permisos restrictivos
        for f in (tmp_path / "creds").iterdir():
            if not f.name.startswith("."):
                mode = f.stat().st_mode & 0o777
                assert mode == 0o600, f"Permisos incorrectos en {f}: {oct(mode)}"

    def test_overwrite(self, tmp_path: Path) -> None:
        store = CredentialStore(credentials_dir=tmp_path / "creds")
        store.store("overwrite", {"version": 1})
        store.store("overwrite", {"version": 2})
        result = store.retrieve("overwrite")
        assert result["version"] == 2


# ═══════════════════════════════════════════════════════════════
# Resolve — tests del motor de resolución runtime
# ═══════════════════════════════════════════════════════════════

class TestResolverContext:
    """Tests del contexto de resolución y helpers."""

    def test_create_resolver_context(self) -> None:
        from config.schema import SomerConfig
        from secrets.resolve import create_resolver_context

        config = SomerConfig()
        ctx = create_resolver_context(config, env={"FOO": "bar"})
        assert ctx.source_config is config
        assert ctx.env == {"FOO": "bar"}
        assert len(ctx.assignments) == 0
        assert len(ctx.warnings) == 0

    def test_push_warning_dedup(self) -> None:
        from config.schema import SomerConfig
        from secrets.resolve import (
            SecretResolverWarning,
            create_resolver_context,
            push_warning,
        )

        ctx = create_resolver_context(SomerConfig(), env={})
        w = SecretResolverWarning(code="TEST", path="a.b", message="msg")
        push_warning(ctx, w)
        push_warning(ctx, w)  # Duplicado
        assert len(ctx.warnings) == 1

    def test_push_assignment(self) -> None:
        from config.schema import SomerConfig
        from secrets.resolve import (
            SecretAssignment,
            create_resolver_context,
            push_assignment,
        )

        ctx = create_resolver_context(SomerConfig(), env={})
        ref = SecretRef.literal("x")
        assignment = SecretAssignment(
            ref=ref,
            path="test.path",
            expected=SecretExpectedValue.STRING,
            apply=lambda v: None,
        )
        push_assignment(ctx, assignment)
        assert len(ctx.assignments) == 1
        assert ctx.assignments[0].path == "test.path"

    def test_collect_secret_input_assignment_literal(self) -> None:
        from config.schema import SomerConfig
        from secrets.resolve import (
            collect_secret_input_assignment,
            create_resolver_context,
        )

        ctx = create_resolver_context(SomerConfig(), env={})
        captured = {}
        collect_secret_input_assignment(
            value="literal:my-secret",
            path="test.literal",
            expected=SecretExpectedValue.STRING,
            context=ctx,
            apply=lambda v: captured.__setitem__("val", v),
        )
        assert len(ctx.assignments) == 1
        assert ctx.assignments[0].ref.source == SecretSource.LITERAL

    def test_collect_secret_input_assignment_inactive(self) -> None:
        from config.schema import SomerConfig
        from secrets.resolve import (
            SecretResolverWarningCode,
            collect_secret_input_assignment,
            create_resolver_context,
        )

        ctx = create_resolver_context(SomerConfig(), env={})
        collect_secret_input_assignment(
            value="$MY_KEY",
            path="test.inactive",
            expected=SecretExpectedValue.STRING,
            context=ctx,
            active=False,
            inactive_reason="disabled",
            apply=lambda v: None,
        )
        # No debe agregar assignment, pero sí warning
        assert len(ctx.assignments) == 0
        assert len(ctx.warnings) == 1
        assert ctx.warnings[0].code == SecretResolverWarningCode.REF_IGNORED_INACTIVE

    def test_collect_secret_input_assignment_non_ref(self) -> None:
        from config.schema import SomerConfig
        from secrets.resolve import (
            collect_secret_input_assignment,
            create_resolver_context,
        )

        ctx = create_resolver_context(SomerConfig(), env={})
        collect_secret_input_assignment(
            value="plain-string-not-a-ref",
            path="test.plain",
            expected=SecretExpectedValue.STRING,
            context=ctx,
            apply=lambda v: None,
        )
        # No es un SecretRef, no debe agregar nada
        assert len(ctx.assignments) == 0
        assert len(ctx.warnings) == 0


class TestSecretsSnapshot:
    """Tests del snapshot de secretos."""

    async def test_prepare_snapshot_empty_config(self) -> None:
        from config.schema import SomerConfig
        from secrets.resolve import prepare_secrets_snapshot

        config = SomerConfig()
        snapshot = await prepare_secrets_snapshot(config, env={})
        assert snapshot.config is not None
        assert snapshot.source_config is not None
        assert len(snapshot.warnings) == 0

    async def test_prepare_snapshot_with_ref(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from config.schema import (
            ProviderAuthConfig,
            ProviderSettings,
            SomerConfig,
        )
        from secrets.resolve import prepare_secrets_snapshot

        monkeypatch.setenv("TEST_PROVIDER_KEY", "sk-resolved")
        config = SomerConfig(
            providers={
                "test_provider": ProviderSettings(
                    auth=ProviderAuthConfig(api_key="$TEST_PROVIDER_KEY"),
                ),
            },
        )
        snapshot = await prepare_secrets_snapshot(
            config, env={"TEST_PROVIDER_KEY": "sk-resolved"},
        )
        assert snapshot.config is not None

    def test_activate_and_get_snapshot(self) -> None:
        from config.schema import SomerConfig
        from secrets.resolve import (
            SecretsRuntimeSnapshot,
            activate_snapshot,
            clear_snapshot,
            get_active_snapshot,
        )

        snapshot = SecretsRuntimeSnapshot(
            source_config=SomerConfig(),
            config=SomerConfig(),
        )
        activate_snapshot(snapshot)
        active = get_active_snapshot()
        assert active is not None
        assert active is snapshot

        clear_snapshot()
        assert get_active_snapshot() is None


# ═══════════════════════════════════════════════════════════════
# Collectors — tests
# ═══════════════════════════════════════════════════════════════

class TestCollectors:
    """Tests de los recolectores de secretos."""

    def test_discover_required_secrets_empty(self) -> None:
        from config.schema import SomerConfig
        from secrets.collectors import discover_required_secrets

        config = SomerConfig()
        candidates = discover_required_secrets(config)
        assert isinstance(candidates, list)
        assert len(candidates) == 0

    def test_discover_required_secrets_provider(self) -> None:
        from config.schema import (
            ProviderAuthConfig,
            ProviderSettings,
            SomerConfig,
        )
        from secrets.collectors import discover_required_secrets

        config = SomerConfig(
            providers={
                "anthropic": ProviderSettings(
                    enabled=True,
                    auth=ProviderAuthConfig(api_key_env="ANTHROPIC_API_KEY"),
                ),
            },
        )
        candidates = discover_required_secrets(config)
        assert len(candidates) == 1
        assert candidates[0]["provider_id"] == "anthropic"
        assert candidates[0]["path"] == "providers.anthropic.auth.api_key"

    def test_discover_required_secrets_channel(self) -> None:
        from config.schema import ChannelConfig, ChannelsConfig, SomerConfig
        from secrets.collectors import discover_required_secrets

        config = SomerConfig(
            channels=ChannelsConfig(
                entries={
                    "telegram": ChannelConfig(
                        enabled=True,
                        config={},
                    ),
                },
            ),
        )
        candidates = discover_required_secrets(config)
        # Telegram requiere bot_token y webhook_secret
        telegram_candidates = [c for c in candidates if c.get("channel_id") == "telegram"]
        assert len(telegram_candidates) == 2

    def test_discover_disabled_not_included(self) -> None:
        from config.schema import (
            ProviderAuthConfig,
            ProviderSettings,
            SomerConfig,
        )
        from secrets.collectors import discover_required_secrets

        config = SomerConfig(
            providers={
                "disabled_provider": ProviderSettings(
                    enabled=False,
                    auth=ProviderAuthConfig(api_key_env="DISABLED_KEY"),
                ),
            },
        )
        candidates = discover_required_secrets(config)
        assert len(candidates) == 0

    def test_list_known_provider_env_vars(self) -> None:
        from secrets.collectors import list_known_provider_env_vars

        vars_list = list_known_provider_env_vars()
        assert "ANTHROPIC_API_KEY" in vars_list
        assert "OPENAI_API_KEY" in vars_list
        assert isinstance(vars_list, list)

    def test_list_known_secret_env_vars(self) -> None:
        from secrets.collectors import list_known_secret_env_vars

        vars_list = list_known_secret_env_vars()
        # Incluye provider y channel env vars
        assert "ANTHROPIC_API_KEY" in vars_list
        assert "TELEGRAM_BOT_TOKEN" in vars_list
        assert sorted(vars_list) == vars_list  # Debe estar ordenada

    def test_collect_all_assignments_empty(self) -> None:
        from config.schema import SomerConfig
        from secrets.collectors import collect_all_assignments
        from secrets.resolve import create_resolver_context

        config = SomerConfig()
        ctx = create_resolver_context(config, env={})
        collect_all_assignments(config=config, context=ctx)
        assert len(ctx.assignments) == 0


# ═══════════════════════════════════════════════════════════════
# Validation — tests
# ═══════════════════════════════════════════════════════════════

class TestValidation:
    """Tests del sistema de validación de secretos."""

    def test_validate_api_key_format_anthropic_valid(self) -> None:
        from secrets.validation import ValidationSeverity, validate_api_key_format

        result = validate_api_key_format(
            "anthropic",
            "sk-ant-abcdefghijklmnopqrst-1234567890",
        )
        assert result.severity == ValidationSeverity.OK

    def test_validate_api_key_format_anthropic_invalid(self) -> None:
        from secrets.validation import ValidationSeverity, validate_api_key_format

        result = validate_api_key_format("anthropic", "invalid-key")
        assert result.severity == ValidationSeverity.WARNING

    def test_validate_api_key_format_empty(self) -> None:
        from secrets.validation import ValidationSeverity, validate_api_key_format

        result = validate_api_key_format("openai", "")
        assert result.severity == ValidationSeverity.ERROR

    def test_validate_api_key_format_openai_valid(self) -> None:
        from secrets.validation import ValidationSeverity, validate_api_key_format

        result = validate_api_key_format(
            "openai",
            "sk-proj-abcdefghijklmnopqrst",
        )
        assert result.severity == ValidationSeverity.OK

    def test_validate_api_key_format_generic(self) -> None:
        from secrets.validation import ValidationSeverity, validate_api_key_format

        # Provider sin patrón específico usa genérico
        result = validate_api_key_format(
            "unknown_provider",
            "some-long-api-key-value-here",
        )
        assert result.severity == ValidationSeverity.OK

    def test_validate_secret_ref_resolvable(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from secrets.validation import ValidationSeverity, validate_secret_ref

        monkeypatch.setenv("VALID_SECRET", "the-value")
        ref = SecretRef.from_env("VALID_SECRET")
        result = validate_secret_ref(ref)
        assert result.severity == ValidationSeverity.OK

    def test_validate_secret_ref_unresolvable(self) -> None:
        from secrets.validation import ValidationSeverity, validate_secret_ref

        ref = SecretRef.from_env("NONEXISTENT_VALIDATE_SECRET_999")
        result = validate_secret_ref(ref)
        assert result.severity == ValidationSeverity.ERROR

    def test_validate_config_secrets_empty(self) -> None:
        from config.schema import SomerConfig
        from secrets.validation import validate_config_secrets

        config = SomerConfig()
        report = validate_config_secrets(config)
        assert report.is_clean
        assert report.total_checked == 0

    def test_validate_config_secrets_provider_missing(self) -> None:
        from config.schema import (
            ProviderAuthConfig,
            ProviderSettings,
            SomerConfig,
        )
        from secrets.validation import validate_config_secrets

        config = SomerConfig(
            providers={
                "anthropic": ProviderSettings(
                    enabled=True,
                    auth=ProviderAuthConfig(),  # Sin API key
                ),
            },
        )
        report = validate_config_secrets(config)
        assert report.total_errors > 0

    def test_validation_report_summary(self) -> None:
        from secrets.validation import (
            ValidationReport,
            ValidationResult,
            ValidationSeverity,
        )

        report = ValidationReport()
        report.add(ValidationResult(
            path="test", severity=ValidationSeverity.OK, message="ok",
        ))
        report.add(ValidationResult(
            path="test2", severity=ValidationSeverity.WARNING, message="warn",
        ))
        summary = report.summary()
        assert "2 verificados" in summary
        assert "1 OK" in summary
        assert "1 warnings" in summary


# ═══════════════════════════════════════════════════════════════
# Rotation — tests
# ═══════════════════════════════════════════════════════════════

class TestRotation:
    """Tests del sistema de rotación de credenciales."""

    def test_rotate_new_credential(self, tmp_path: Path) -> None:
        from secrets.rotation import CredentialRotator

        store = CredentialStore(credentials_dir=tmp_path / "creds")
        rotator = CredentialRotator(store, backup_dir=tmp_path / "backups")

        result = rotator.rotate(
            service="anthropic",
            key="api_key",
            new_value="sk-ant-newkey-abcdefghijklmnopqrst",
            validate=True,
        )
        assert result.success
        assert result.previous_backup_path is None  # No había valor previo

        # Verificar que se almacenó
        creds = store.retrieve("anthropic")
        assert creds["api_key"] == "sk-ant-newkey-abcdefghijklmnopqrst"

    def test_rotate_with_backup(self, tmp_path: Path) -> None:
        from secrets.rotation import CredentialRotator

        store = CredentialStore(credentials_dir=tmp_path / "creds")
        store.store("anthropic", {"api_key": "sk-ant-old-key-abcdefg123456789"})

        rotator = CredentialRotator(store, backup_dir=tmp_path / "backups")
        result = rotator.rotate(
            service="anthropic",
            key="api_key",
            new_value="sk-ant-new-key-abcdefg987654321",
            validate=True,
        )
        assert result.success
        assert result.previous_backup_path is not None

        # Verificar backup existe
        backup_path = Path(result.previous_backup_path)
        assert backup_path.exists()
        backup_data = json.loads(backup_path.read_text())
        assert backup_data["api_key"] == "sk-ant-old-key-abcdefg123456789"

        # Verificar nuevo valor
        creds = store.retrieve("anthropic")
        assert creds["api_key"] == "sk-ant-new-key-abcdefg987654321"

    def test_rotate_from_ref(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from secrets.rotation import CredentialRotator

        monkeypatch.setenv("NEW_KEY", "sk-ant-from-ref-abcdefg111111111")
        store = CredentialStore(credentials_dir=tmp_path / "creds")
        rotator = CredentialRotator(store, backup_dir=tmp_path / "backups")

        ref = SecretRef.from_env("NEW_KEY")
        result = rotator.rotate_from_ref(
            service="test-svc",
            key="api_key",
            ref=ref,
            validate=False,
        )
        assert result.success
        creds = store.retrieve("test-svc")
        assert creds["api_key"] == "sk-ant-from-ref-abcdefg111111111"

    def test_rotate_from_ref_unresolvable(self, tmp_path: Path) -> None:
        from secrets.rotation import CredentialRotator

        store = CredentialStore(credentials_dir=tmp_path / "creds")
        rotator = CredentialRotator(store, backup_dir=tmp_path / "backups")

        ref = SecretRef.from_env("NONEXISTENT_ROTATION_ENV")
        result = rotator.rotate_from_ref(
            service="test-svc",
            key="api_key",
            ref=ref,
        )
        assert not result.success
        assert "resolver" in result.message.lower() or "No se pudo" in result.message

    def test_rotation_plan(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from secrets.rotation import CredentialRotator, RotationPlan

        monkeypatch.setenv("PLAN_KEY", "plan-value-123")
        store = CredentialStore(credentials_dir=tmp_path / "creds")
        rotator = CredentialRotator(store, backup_dir=tmp_path / "backups")

        plan = RotationPlan()
        plan.add_rotation(
            service="plan-svc",
            key="token",
            new_ref=SecretRef.from_env("PLAN_KEY"),
            reason="rotación de prueba",
        )
        assert plan.has_changes

        results = rotator.execute_plan(plan, validate=False)
        assert len(results) == 1
        assert results[0].success

    def test_list_backups(self, tmp_path: Path) -> None:
        from secrets.rotation import CredentialRotator

        store = CredentialStore(credentials_dir=tmp_path / "creds")
        store.store("svc-a", {"key": "val-a"})
        rotator = CredentialRotator(store, backup_dir=tmp_path / "backups")

        # Rotar para crear backup
        rotator.rotate("svc-a", "key", "new-val", validate=False)
        backups = rotator.list_backups()
        assert len(backups) == 1
        assert backups[0]["service"] == "svc-a"

    def test_restore_from_backup(self, tmp_path: Path) -> None:
        from secrets.rotation import CredentialRotator

        store = CredentialStore(credentials_dir=tmp_path / "creds")
        store.store("restore-svc", {"key": "original"})
        rotator = CredentialRotator(store, backup_dir=tmp_path / "backups")

        # Rotar y luego restaurar
        result = rotator.rotate("restore-svc", "key", "rotated", validate=False)
        assert result.success
        assert result.previous_backup_path is not None

        # Restaurar
        restored = rotator.restore_from_backup(result.previous_backup_path)
        assert restored

        creds = store.retrieve("restore-svc")
        assert creds["key"] == "original"


# ═══════════════════════════════════════════════════════════════
# Apply — tests
# ═══════════════════════════════════════════════════════════════

class TestApply:
    """Tests de aplicación de secretos al runtime."""

    def test_resolve_provider_key_env(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from config.schema import (
            ProviderAuthConfig,
            ProviderSettings,
            SomerConfig,
        )
        from secrets.apply import resolve_provider_key

        monkeypatch.setenv("MY_PROVIDER_KEY", "sk-from-env")
        config = SomerConfig(
            providers={
                "test": ProviderSettings(
                    auth=ProviderAuthConfig(api_key_env="MY_PROVIDER_KEY"),
                ),
            },
        )
        key = resolve_provider_key("test", config)
        assert key == "sk-from-env"

    def test_resolve_provider_key_literal(self) -> None:
        from config.schema import (
            ProviderAuthConfig,
            ProviderSettings,
            SomerConfig,
        )
        from secrets.apply import resolve_provider_key

        config = SomerConfig(
            providers={
                "test": ProviderSettings(
                    auth=ProviderAuthConfig(api_key="sk-literal-key"),
                ),
            },
        )
        key = resolve_provider_key("test", config)
        assert key == "sk-literal-key"

    def test_resolve_provider_key_from_ref_string(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from config.schema import (
            ProviderAuthConfig,
            ProviderSettings,
            SomerConfig,
        )
        from secrets.apply import resolve_provider_key

        monkeypatch.setenv("REF_KEY", "sk-from-ref")
        config = SomerConfig(
            providers={
                "test": ProviderSettings(
                    auth=ProviderAuthConfig(api_key="$REF_KEY"),
                ),
            },
        )
        key = resolve_provider_key("test", config)
        assert key == "sk-from-ref"

    def test_resolve_provider_key_store(self, tmp_path: Path) -> None:
        from config.schema import (
            ProviderAuthConfig,
            ProviderSettings,
            SomerConfig,
        )
        from secrets.apply import resolve_provider_key

        store = CredentialStore(credentials_dir=tmp_path / "creds")
        store.store("test", {"api_key": "sk-from-store"})
        config = SomerConfig(
            providers={
                "test": ProviderSettings(
                    auth=ProviderAuthConfig(),
                ),
            },
        )
        key = resolve_provider_key("test", config, store=store)
        assert key == "sk-from-store"

    def test_resolve_provider_key_file(self, tmp_path: Path) -> None:
        from config.schema import (
            ProviderAuthConfig,
            ProviderSettings,
            SomerConfig,
        )
        from secrets.apply import resolve_provider_key

        key_file = tmp_path / "api_key.txt"
        key_file.write_text("sk-from-file")
        config = SomerConfig(
            providers={
                "test": ProviderSettings(
                    auth=ProviderAuthConfig(api_key_file=str(key_file)),
                ),
            },
        )
        key = resolve_provider_key("test", config)
        assert key == "sk-from-file"

    def test_resolve_provider_key_nonexistent(self) -> None:
        from config.schema import SomerConfig
        from secrets.apply import resolve_provider_key

        config = SomerConfig()
        key = resolve_provider_key("nonexistent", config)
        assert key is None

    def test_resolve_channel_secret_from_config(self) -> None:
        from config.schema import ChannelConfig, ChannelsConfig, SomerConfig
        from secrets.apply import resolve_channel_secret

        config = SomerConfig(
            channels=ChannelsConfig(
                entries={
                    "telegram": ChannelConfig(
                        enabled=True,
                        config={"bot_token": "1234:ABCDefgh"},
                    ),
                },
            ),
        )
        token = resolve_channel_secret("telegram", "bot_token", config)
        assert token == "1234:ABCDefgh"

    def test_resolve_channel_secret_from_env(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from config.schema import ChannelConfig, ChannelsConfig, SomerConfig
        from secrets.apply import resolve_channel_secret

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-bot-token")
        config = SomerConfig(
            channels=ChannelsConfig(
                entries={
                    "telegram": ChannelConfig(enabled=True, config={}),
                },
            ),
        )
        token = resolve_channel_secret("telegram", "bot_token", config)
        assert token == "env-bot-token"

    def test_resolve_channel_secret_from_ref(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from config.schema import ChannelConfig, ChannelsConfig, SomerConfig
        from secrets.apply import resolve_channel_secret

        monkeypatch.setenv("TG_TOKEN", "ref-token-value")
        config = SomerConfig(
            channels=ChannelsConfig(
                entries={
                    "telegram": ChannelConfig(
                        enabled=True,
                        config={"bot_token": "$TG_TOKEN"},
                    ),
                },
            ),
        )
        token = resolve_channel_secret("telegram", "bot_token", config)
        assert token == "ref-token-value"

    def test_scrub_secret_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from secrets.apply import scrub_secret_env_vars

        env = {
            "ANTHROPIC_API_KEY": "sk-secret",
            "OPENAI_API_KEY": "sk-openai",
            "PATH": "/usr/bin",
            "HOME": "/home/user",
        }
        cleaned = scrub_secret_env_vars(env)
        assert "ANTHROPIC_API_KEY" not in cleaned
        assert "OPENAI_API_KEY" not in cleaned
        assert cleaned["PATH"] == "/usr/bin"
        assert cleaned["HOME"] == "/home/user"
