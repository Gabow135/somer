"""Tests para media/pipeline.py — transcripción de audio."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from media.pipeline import MediaFile, MediaPipeline, MediaType


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def pipeline(tmp_path: Any) -> MediaPipeline:
    return MediaPipeline(temp_dir=tmp_path)


@pytest.fixture
def audio_file(tmp_path: Any) -> MediaFile:
    """Crea un MediaFile de audio dummy."""
    audio_path = tmp_path / "test_voice.ogg"
    audio_path.write_bytes(b"\x00" * 100)
    return MediaFile(
        path=audio_path,
        media_type=MediaType.AUDIO,
        mime_type="audio/ogg",
        size_bytes=100,
        duration_secs=5.0,
    )


@pytest.fixture
def image_file(tmp_path: Any) -> MediaFile:
    """Crea un MediaFile de imagen dummy."""
    img_path = tmp_path / "test.png"
    img_path.write_bytes(b"\x89PNG" + b"\x00" * 50)
    return MediaFile(
        path=img_path,
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=54,
    )


# ── transcribe ────────────────────────────────────────────────


class TestTranscribe:
    """Tests para MediaPipeline.transcribe()."""

    @pytest.mark.asyncio
    async def test_rejects_non_audio(
        self, pipeline: MediaPipeline, image_file: MediaFile
    ) -> None:
        with pytest.raises(Exception, match="no soportada"):
            await pipeline.transcribe(image_file)

    @pytest.mark.asyncio
    async def test_openai_api_used_when_key_present(
        self, pipeline: MediaPipeline, audio_file: MediaFile
    ) -> None:
        """Si OPENAI_API_KEY está configurada, intenta la API de OpenAI."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test123"}):
            with patch.object(
                pipeline, "_transcribe_openai", return_value="Hola mundo"
            ) as mock_openai:
                result = await pipeline.transcribe(audio_file)
                mock_openai.assert_called_once_with(audio_file.path, "sk-test123")
                assert result == "Hola mundo"

    @pytest.mark.asyncio
    async def test_falls_back_to_local_whisper(
        self, pipeline: MediaPipeline, audio_file: MediaFile
    ) -> None:
        """Si OpenAI falla, intenta whisper local."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            with patch.object(
                pipeline, "_transcribe_openai", side_effect=Exception("API error")
            ):
                with patch.object(
                    pipeline, "_transcribe_local_whisper", return_value="Texto local"
                ) as mock_local:
                    result = await pipeline.transcribe(audio_file)
                    mock_local.assert_called_once()
                    assert result == "Texto local"

    @pytest.mark.asyncio
    async def test_returns_error_when_both_fail(
        self, pipeline: MediaPipeline, audio_file: MediaFile
    ) -> None:
        """Si ambos métodos fallan, retorna mensaje de error."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            with patch.object(
                pipeline, "_transcribe_local_whisper", return_value=""
            ):
                result = await pipeline.transcribe(audio_file)
                assert "no disponible" in result.lower()

    @pytest.mark.asyncio
    async def test_skips_openai_when_no_key(
        self, pipeline: MediaPipeline, audio_file: MediaFile
    ) -> None:
        """Sin OPENAI_API_KEY, no intenta la API."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            with patch.object(
                pipeline, "_transcribe_openai"
            ) as mock_openai:
                with patch.object(
                    pipeline, "_transcribe_local_whisper", return_value="Local ok"
                ):
                    result = await pipeline.transcribe(audio_file)
                    mock_openai.assert_not_called()
                    assert result == "Local ok"

    @pytest.mark.asyncio
    async def test_openai_empty_result_falls_through(
        self, pipeline: MediaPipeline, audio_file: MediaFile
    ) -> None:
        """Si OpenAI retorna vacío, intenta local."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            with patch.object(
                pipeline, "_transcribe_openai", return_value=""
            ):
                with patch.object(
                    pipeline, "_transcribe_local_whisper", return_value="Fallback"
                ) as mock_local:
                    result = await pipeline.transcribe(audio_file)
                    mock_local.assert_called_once()
                    assert result == "Fallback"


# ── _transcribe_local_whisper ─────────────────────────────────


class TestTranscribeLocalWhisper:
    """Tests para _transcribe_local_whisper."""

    @pytest.mark.asyncio
    async def test_reads_output_file(
        self, pipeline: MediaPipeline, audio_file: MediaFile, tmp_path: Any
    ) -> None:
        """Si whisper produce un .txt, lo lee y lo retorna."""
        # Crear el archivo que whisper produciría
        expected_txt = tmp_path / "test_voice.txt"
        expected_txt.write_text("Texto transcrito", encoding="utf-8")

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with patch("subprocess.run", side_effect=fake_run):
            result = await pipeline._transcribe_local_whisper(audio_file.path)
            assert result == "Texto transcrito"

    @pytest.mark.asyncio
    async def test_returns_empty_on_failure(
        self, pipeline: MediaPipeline, audio_file: MediaFile
    ) -> None:
        """Si whisper no está instalado, retorna vacío."""
        with patch(
            "subprocess.run", side_effect=FileNotFoundError("whisper not found")
        ):
            result = await pipeline._transcribe_local_whisper(audio_file.path)
            assert result == ""


# ── process ───────────────────────────────────────────────────


class TestProcess:
    """Tests para MediaPipeline.process()."""

    def test_detects_audio_type(self, pipeline: MediaPipeline, tmp_path: Any) -> None:
        ogg = tmp_path / "voice.ogg"
        ogg.write_bytes(b"\x00" * 50)
        result = pipeline.process(str(ogg))
        assert result.media_type == MediaType.AUDIO

    def test_detects_image_type(self, pipeline: MediaPipeline, tmp_path: Any) -> None:
        png = tmp_path / "photo.png"
        png.write_bytes(b"\x89PNG" + b"\x00" * 50)
        result = pipeline.process(str(png))
        assert result.media_type == MediaType.IMAGE

    def test_raises_on_missing_file(self, pipeline: MediaPipeline) -> None:
        with pytest.raises(Exception, match="no encontrado"):
            pipeline.process("/nonexistent/file.ogg")
