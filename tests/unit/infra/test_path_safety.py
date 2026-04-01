"""Tests para infra/path_safety.py — Protección contra path traversal."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from infra.path_safety import (
    PathEscapeError,
    PathSafetyValidator,
    is_path_inside,
    safe_join,
    sanitize_filename,
)


class TestIsPathInside:
    """Tests de verificación de paths."""

    def test_child_is_inside(self) -> None:
        assert is_path_inside(Path("/home/user"), Path("/home/user/docs")) is True

    def test_same_is_inside(self) -> None:
        assert is_path_inside(Path("/home/user"), Path("/home/user")) is True

    def test_parent_not_inside(self) -> None:
        assert is_path_inside(Path("/home/user"), Path("/home")) is False

    def test_sibling_not_inside(self) -> None:
        assert is_path_inside(Path("/home/user"), Path("/home/other")) is False

    def test_traversal_not_inside(self) -> None:
        assert is_path_inside(Path("/home/user"), Path("/home/user/../other")) is False


class TestPathSafetyValidator:
    """Tests del validador de seguridad."""

    def setup_method(self) -> None:
        self._tmpdir = Path(tempfile.mkdtemp())
        (self._tmpdir / "safe").mkdir()
        (self._tmpdir / "safe" / "file.txt").write_text("ok")
        self.validator = PathSafetyValidator(self._tmpdir / "safe", "test-boundary")

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_safe_path(self) -> None:
        """Path dentro del boundary es válido."""
        result = self.validator.validate(self._tmpdir / "safe" / "file.txt")
        assert result.name == "file.txt"

    def test_escape_raises(self) -> None:
        """Path fuera del boundary lanza error."""
        with pytest.raises(PathEscapeError):
            self.validator.validate(self._tmpdir / "outside")

    def test_traversal_raises(self) -> None:
        """Path traversal lanza error."""
        with pytest.raises(PathEscapeError):
            self.validator.validate(self._tmpdir / "safe" / ".." / ".." / "etc" / "passwd")

    def test_is_safe(self) -> None:
        """is_safe no lanza excepciones."""
        assert self.validator.is_safe(self._tmpdir / "safe" / "file.txt") is True
        assert self.validator.is_safe(self._tmpdir / "outside") is False

    def test_validate_relative(self) -> None:
        """Valida paths relativos."""
        result = self.validator.validate_relative("file.txt")
        assert "file.txt" in str(result)

    def test_validate_relative_traversal(self) -> None:
        """Traversal en path relativo lanza error."""
        with pytest.raises(PathEscapeError):
            self.validator.validate_relative("../../etc/passwd")


class TestSafeJoin:
    """Tests de safe_join."""

    def setup_method(self) -> None:
        self._tmpdir = Path(tempfile.mkdtemp())
        (self._tmpdir / "subdir").mkdir()

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_safe_join_normal(self) -> None:
        """Join normal funciona."""
        result = safe_join(self._tmpdir, "subdir")
        assert result == (self._tmpdir / "subdir").resolve()

    def test_safe_join_absolute_rejects(self) -> None:
        """Componente absoluto es rechazado."""
        with pytest.raises(PathEscapeError):
            safe_join(self._tmpdir, "/etc/passwd")

    def test_safe_join_traversal_rejects(self) -> None:
        """Traversal es rechazado."""
        with pytest.raises(PathEscapeError):
            safe_join(self._tmpdir, "..", "..", "etc", "passwd")


class TestSanitizeFilename:
    """Tests de sanitización de nombres de archivo."""

    def test_normal_name(self) -> None:
        assert sanitize_filename("document.txt") == "document.txt"

    def test_dangerous_chars(self) -> None:
        sanitized = sanitize_filename('file/with\\bad:chars*?.txt')
        assert "/" not in sanitized
        assert "\\" not in sanitized
        assert ":" not in sanitized
        assert "*" not in sanitized
        assert "?" not in sanitized

    def test_empty(self) -> None:
        assert sanitize_filename("") == "unnamed"

    def test_windows_reserved(self) -> None:
        assert sanitize_filename("CON.txt").startswith("_")
        assert sanitize_filename("NUL").startswith("_")

    def test_leading_dot(self) -> None:
        """No empieza con punto."""
        sanitized = sanitize_filename(".hidden")
        assert not sanitized.startswith(".")

    def test_max_length(self) -> None:
        long_name = "a" * 300
        sanitized = sanitize_filename(long_name, max_length=100)
        assert len(sanitized) == 100
