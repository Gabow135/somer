"""Tests para el módulo self_improve."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from self_improve.paths import (
    get_project_root,
    get_somer_home,
    list_project_skills,
    get_all_env_paths,
    get_project_file,
    _is_somer_root,
)
from self_improve.learner import PatternLearner, LearnedStore, LearnedPattern
from self_improve.engine import SelfImproveEngine


# ── Paths ─────────────────────────────────────────────────


class TestPaths:

    def test_get_somer_home_default(self):
        # Si SOMER_HOME está seteado, lo usa; si no, usa ~/.somer
        env_home = os.environ.get("SOMER_HOME")
        home = get_somer_home()
        if env_home:
            assert home == Path(env_home)
        else:
            assert home == Path.home() / ".somer"

    def test_get_somer_home_custom(self):
        with patch.dict(os.environ, {"SOMER_HOME": "/tmp/test_somer"}):
            home = get_somer_home()
            assert home == Path("/tmp/test_somer")

    def test_get_project_root_finds_current(self):
        root = get_project_root()
        assert root is not None
        assert (root / "pyproject.toml").exists()
        assert (root / "shared").is_dir()

    def test_get_project_root_custom_env(self):
        root = get_project_root()
        if root:
            with patch.dict(os.environ, {"SOMER_PROJECT_ROOT": str(root)}):
                found = get_project_root()
                assert found == root

    def test_list_project_skills(self):
        skills = list_project_skills()
        assert len(skills) > 0
        assert all(s.name == "SKILL.md" for s in skills)

    def test_get_project_file_exists(self):
        f = get_project_file("pyproject.toml")
        assert f is not None
        assert f.exists()

    def test_get_project_file_not_exists(self):
        f = get_project_file("nonexistent_file_xyz.py")
        assert f is None

    def test_is_somer_root_true(self):
        root = get_project_root()
        if root:
            assert _is_somer_root(root) is True

    def test_is_somer_root_false(self):
        assert _is_somer_root(Path("/tmp")) is False

    def test_get_all_env_paths(self):
        paths = get_all_env_paths()
        # Al menos el home .env debería existir
        assert isinstance(paths, list)


# ── Learner ───────────────────────────────────────────────


class TestLearner:

    def test_scan_and_learn(self):
        learner = PatternLearner()
        # Puede ya tener patrones del test anterior, limpiar
        new = learner.scan_and_learn()
        assert isinstance(new, int)
        assert new >= 0

    def test_get_patterns(self):
        learner = PatternLearner()
        learner.scan_and_learn()
        patterns = learner.get_patterns()
        assert isinstance(patterns, list)
        assert len(patterns) > 0

    def test_get_context_keywords(self):
        learner = PatternLearner()
        learner.scan_and_learn()
        keywords = learner.get_context_keywords()
        assert isinstance(keywords, dict)
        assert len(keywords) > 0
        # Cada entrada debería ser una lista de regex strings
        for env_var, kw_list in keywords.items():
            assert isinstance(kw_list, list)
            assert len(kw_list) > 0

    def test_stats(self):
        learner = PatternLearner()
        learner.scan_and_learn()
        stats = learner.stats
        assert "total_patterns" in stats
        assert "skills_scanned" in stats
        assert stats["skills_scanned"] > 0

    def test_add_pattern_manual(self):
        learner = PatternLearner()
        pat = LearnedPattern(
            env_var="TEST_MANUAL_KEY",
            service="test-service",
            description="Test manual",
            kind="api_key",
        )
        added = learner.add_pattern(pat)
        assert added is True
        # Duplicate should return False
        added2 = learner.add_pattern(pat)
        assert added2 is False
        # Cleanup
        learner.remove_pattern("TEST_MANUAL_KEY")

    def test_remove_pattern(self):
        learner = PatternLearner()
        pat = LearnedPattern(
            env_var="TEST_REMOVE_KEY",
            service="test-service",
            description="Test remove",
        )
        learner.add_pattern(pat)
        removed = learner.remove_pattern("TEST_REMOVE_KEY")
        assert removed is True
        removed2 = learner.remove_pattern("TEST_REMOVE_KEY")
        assert removed2 is False

    def test_learned_store_serialization(self):
        store = LearnedStore(
            patterns=[
                LearnedPattern(
                    env_var="TEST_KEY",
                    service="test",
                    description="desc",
                ),
            ],
            last_scan=1000.0,
            skills_scanned=5,
        )
        d = store.to_dict()
        restored = LearnedStore.from_dict(d)
        assert len(restored.patterns) == 1
        assert restored.patterns[0].env_var == "TEST_KEY"
        assert restored.last_scan == 1000.0


# ── Engine ────────────────────────────────────────────────


class TestEngine:

    def test_learn_from_skills(self):
        engine = SelfImproveEngine()
        result = engine.learn_from_skills()
        assert "new_patterns" in result
        assert "total_patterns" in result
        assert "skills_scanned" in result
        assert result["skills_scanned"] > 0

    def test_get_status(self):
        engine = SelfImproveEngine()
        status = engine.get_status()
        assert "project_root" in status
        assert "somer_home" in status
        assert "learner" in status
        assert "restart_pending" in status
        assert status["project_root"] is not None

    def test_validate_python_valid(self):
        engine = SelfImproveEngine()
        result = engine.validate_python("def foo(): return 1")
        assert result.valid is True
        assert result.errors == []

    def test_validate_python_invalid(self):
        engine = SelfImproveEngine()
        result = engine.validate_python("def foo( return 1")
        assert result.valid is False
        assert len(result.errors) > 0

    def test_patch_dry_run(self):
        engine = SelfImproveEngine()
        result = engine.patch_file(
            "self_improve/__init__.py",
            "Self-improve",
            "Self-improve test",
            dry_run=True,
        )
        assert result.success is True
        assert result.backup_path == ""

    def test_patch_file_not_found(self):
        engine = SelfImproveEngine()
        result = engine.patch_file(
            "nonexistent_xyz.py",
            "old",
            "new",
        )
        assert result.success is False
        assert "no encontrado" in result.error.lower() or "not found" in result.error.lower()

    def test_patch_old_content_not_found(self):
        engine = SelfImproveEngine()
        result = engine.patch_file(
            "self_improve/__init__.py",
            "THIS_CONTENT_DOES_NOT_EXIST_XYZ",
            "new",
        )
        assert result.success is False
        assert "no encontrado" in result.error.lower()

    def test_get_improvement_history(self):
        engine = SelfImproveEngine()
        history = engine.get_improvement_history(limit=5)
        assert isinstance(history, list)

    def test_get_learned_patterns(self):
        engine = SelfImproveEngine()
        patterns = engine.get_learned_patterns()
        assert isinstance(patterns, list)

    def test_request_restart_sentinel(self):
        engine = SelfImproveEngine()
        success = engine.request_restart("test restart")
        assert success is True
        # Cleanup: acknowledge the sentinel
        from infra.restart_sentinel import RestartSentinel
        sentinel = RestartSentinel()
        sentinel.acknowledge_restart()
