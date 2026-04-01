"""Text-to-speech engine — síntesis de voz con múltiples providers."""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional

from shared.errors import SomerError

logger = logging.getLogger(__name__)


class TTSError(SomerError):
    """Error en el motor de text-to-speech."""


class TTSProvider(ABC):
    """Interfaz base para providers de TTS."""

    name: str = "base"

    @abstractmethod
    async def synthesize(self, text: str, voice: Optional[str] = None) -> bytes:
        """Sintetiza texto a audio (WAV/MP3 bytes).

        Args:
            text: Texto a sintetizar.
            voice: Identificador de voz (depende del provider).

        Returns:
            bytes con los datos de audio.
        """
        ...

    async def list_voices(self) -> List[str]:
        """Lista las voces disponibles en este provider."""
        return []

    async def health_check(self) -> bool:
        """Verifica si el provider está disponible."""
        try:
            data = await self.synthesize("test", None)
            return len(data) > 0
        except Exception:
            return False


class SystemTTSProvider(TTSProvider):
    """TTS usando comandos nativos del sistema operativo.

    - macOS: ``say`` (generación directa a AIFF)
    - Linux: ``espeak`` (generación a WAV)
    """

    name = "system"

    def __init__(self) -> None:
        self._system = platform.system().lower()

    async def synthesize(self, text: str, voice: Optional[str] = None) -> bytes:
        if not text.strip():
            raise TTSError("Texto vacío para sintetizar")

        if self._system == "darwin":
            return await self._synthesize_macos(text, voice)
        elif self._system == "linux":
            return await self._synthesize_linux(text, voice)
        else:
            raise TTSError(f"TTS del sistema no soportado en {self._system}")

    async def _synthesize_macos(self, text: str, voice: Optional[str]) -> bytes:
        """Sintetiza usando ``say`` en macOS."""
        with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cmd = ["say", "-o", tmp_path]
            if voice:
                cmd.extend(["-v", voice])
            cmd.append(text)

            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)

            if proc.returncode != 0:
                raise TTSError(f"say falló: {stderr.decode(errors='replace')}")

            return Path(tmp_path).read_bytes()
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def _synthesize_linux(self, text: str, voice: Optional[str]) -> bytes:
        """Sintetiza usando ``espeak`` en Linux."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cmd = ["espeak", "-w", tmp_path]
            if voice:
                cmd.extend(["-v", voice])
            cmd.append(text)

            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)

            if proc.returncode != 0:
                raise TTSError(f"espeak falló: {stderr.decode(errors='replace')}")

            return Path(tmp_path).read_bytes()
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def list_voices(self) -> List[str]:
        if self._system == "darwin":
            proc = await asyncio.create_subprocess_exec(
                "say", "-v", "?",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            lines = stdout.decode(errors="replace").strip().splitlines()
            return [line.split()[0] for line in lines if line.strip()]
        elif self._system == "linux":
            proc = await asyncio.create_subprocess_exec(
                "espeak", "--voices",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            lines = stdout.decode(errors="replace").strip().splitlines()
            # Skip header line
            voices: List[str] = []
            for line in lines[1:]:
                parts = line.split()
                if len(parts) >= 4:
                    voices.append(parts[3])  # Voice name
            return voices
        return []


class ElevenLabsTTSProvider(TTSProvider):
    """TTS usando la API de ElevenLabs.

    Requiere ELEVENLABS_API_KEY en variables de entorno.
    Genera audio MP3 de alta calidad.
    """

    name = "elevenlabs"

    # Voz por defecto: "Rachel" (una de las gratuitas)
    DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_voice_id: Optional[str] = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        self._default_voice_id = default_voice_id or self.DEFAULT_VOICE_ID

    async def synthesize(self, text: str, voice: Optional[str] = None) -> bytes:
        if not self._api_key:
            raise TTSError("ELEVENLABS_API_KEY no configurada")

        if not text.strip():
            raise TTSError("Texto vacío para sintetizar")

        try:
            import httpx
        except ImportError:
            raise TTSError("httpx no instalado: pip install httpx")

        voice_id = voice or self._default_voice_id

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": self._api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json={
                    "text": text,
                    "model_id": "eleven_monolingual_v1",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                    },
                },
            )
            if response.status_code == 401:
                raise TTSError("API key de ElevenLabs inválida")
            response.raise_for_status()
            return response.content

    async def list_voices(self) -> List[str]:
        if not self._api_key:
            return []

        try:
            import httpx
        except ImportError:
            return []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    "https://api.elevenlabs.io/v1/voices",
                    headers={"xi-api-key": self._api_key},
                )
                response.raise_for_status()
                data = response.json()
                return [v["voice_id"] for v in data.get("voices", [])]
        except Exception:
            return []


class TTSEngine:
    """Motor de TTS con registro de providers.

    Selecciona el provider adecuado y sintetiza texto.

    Uso::

        engine = TTSEngine()
        engine.register_provider(SystemTTSProvider())
        engine.register_provider(ElevenLabsTTSProvider())

        audio = await engine.speak("Hola mundo")
        audio = await engine.speak("Hello", provider="elevenlabs", voice="rachel")
    """

    def __init__(self) -> None:
        self._providers: Dict[str, TTSProvider] = {}
        self._default_provider: Optional[str] = None

    def register_provider(
        self, provider: TTSProvider, *, default: bool = False
    ) -> None:
        """Registra un provider de TTS."""
        self._providers[provider.name] = provider
        if default or self._default_provider is None:
            self._default_provider = provider.name
        logger.info("TTS provider '%s' registrado", provider.name)

    def unregister_provider(self, name: str) -> bool:
        """Desregistra un provider."""
        removed = self._providers.pop(name, None)
        if removed and self._default_provider == name:
            self._default_provider = next(iter(self._providers), None)
        return removed is not None

    @property
    def provider_names(self) -> List[str]:
        return list(self._providers.keys())

    async def speak(
        self,
        text: str,
        *,
        provider: Optional[str] = None,
        voice: Optional[str] = None,
    ) -> bytes:
        """Sintetiza texto a audio.

        Args:
            text: Texto a sintetizar.
            provider: Nombre del provider (usa default si no se especifica).
            voice: Voz a usar (depende del provider).

        Returns:
            bytes con datos de audio.
        """
        provider_name = provider or self._default_provider
        if provider_name is None or provider_name not in self._providers:
            raise TTSError(
                f"Provider TTS no disponible: {provider_name}. "
                f"Registrados: {list(self._providers.keys())}"
            )

        tts = self._providers[provider_name]
        logger.info("Sintetizando %d chars con '%s'", len(text), provider_name)
        return await tts.synthesize(text, voice)

    async def list_voices(self, provider: Optional[str] = None) -> Dict[str, List[str]]:
        """Lista voces disponibles por provider."""
        result: Dict[str, List[str]] = {}
        targets = (
            [self._providers[provider]] if provider and provider in self._providers
            else list(self._providers.values())
        )
        for p in targets:
            try:
                voices = await p.list_voices()
                result[p.name] = voices
            except Exception:
                result[p.name] = []
        return result
