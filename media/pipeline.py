"""Media pipeline — detección, metadatos y procesamiento de archivos multimedia."""

from __future__ import annotations

import logging
import mimetypes
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.constants import DEFAULT_HOME
from shared.errors import SomerError

logger = logging.getLogger(__name__)

TEMP_MEDIA_DIR = DEFAULT_HOME / "media_tmp"

# Asegurar que mimetypes está inicializado
mimetypes.init()


class MediaError(SomerError):
    """Error en el pipeline de medios."""


class MediaType(str, Enum):
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"


# Mapeo de extensiones a MediaType
_EXT_TO_TYPE: Dict[str, MediaType] = {
    # Imágenes
    ".jpg": MediaType.IMAGE, ".jpeg": MediaType.IMAGE, ".png": MediaType.IMAGE,
    ".gif": MediaType.IMAGE, ".bmp": MediaType.IMAGE, ".webp": MediaType.IMAGE,
    ".svg": MediaType.IMAGE, ".ico": MediaType.IMAGE, ".tiff": MediaType.IMAGE,
    # Audio
    ".mp3": MediaType.AUDIO, ".wav": MediaType.AUDIO, ".ogg": MediaType.AUDIO,
    ".flac": MediaType.AUDIO, ".aac": MediaType.AUDIO, ".wma": MediaType.AUDIO,
    ".m4a": MediaType.AUDIO, ".opus": MediaType.AUDIO,
    # Video
    ".mp4": MediaType.VIDEO, ".avi": MediaType.VIDEO, ".mkv": MediaType.VIDEO,
    ".mov": MediaType.VIDEO, ".wmv": MediaType.VIDEO, ".webm": MediaType.VIDEO,
    ".flv": MediaType.VIDEO, ".m4v": MediaType.VIDEO,
    # Documentos
    ".pdf": MediaType.DOCUMENT, ".doc": MediaType.DOCUMENT,
    ".docx": MediaType.DOCUMENT, ".xls": MediaType.DOCUMENT,
    ".xlsx": MediaType.DOCUMENT, ".ppt": MediaType.DOCUMENT,
    ".pptx": MediaType.DOCUMENT, ".txt": MediaType.DOCUMENT,
    ".csv": MediaType.DOCUMENT, ".rtf": MediaType.DOCUMENT,
    ".odt": MediaType.DOCUMENT, ".ods": MediaType.DOCUMENT,
}


@dataclass
class MediaFile:
    """Representación de un archivo multimedia procesado."""

    path: Path
    media_type: MediaType
    mime_type: str
    size_bytes: int
    duration_secs: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def _detect_media_type(file_path: Path) -> MediaType:
    """Detecta el tipo de media por extensión."""
    ext = file_path.suffix.lower()
    mt = _EXT_TO_TYPE.get(ext)
    if mt is not None:
        return mt

    # Fallback por mime type
    mime, _ = mimetypes.guess_type(str(file_path))
    if mime:
        category = mime.split("/")[0]
        type_map = {"image": MediaType.IMAGE, "audio": MediaType.AUDIO,
                     "video": MediaType.VIDEO}
        if category in type_map:
            return type_map[category]

    return MediaType.DOCUMENT


def _get_mime_type(file_path: Path) -> str:
    """Obtiene el MIME type del archivo."""
    mime, _ = mimetypes.guess_type(str(file_path))
    return mime or "application/octet-stream"


class MediaPipeline:
    """Pipeline de procesamiento multimedia.

    Detecta tipo, extrae metadatos y provee operaciones sobre
    archivos de imagen, audio, video y documentos.

    Uso::

        pipeline = MediaPipeline()
        media = pipeline.process("/path/to/image.png")
        text = await pipeline.extract_text(media)
    """

    def __init__(self, temp_dir: Optional[Path] = None) -> None:
        self._temp_dir = temp_dir or TEMP_MEDIA_DIR
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    def process(self, file_path: str) -> MediaFile:
        """Procesa un archivo: detecta tipo, extrae metadatos básicos.

        Args:
            file_path: Ruta al archivo.

        Returns:
            MediaFile con la información extraída.

        Raises:
            MediaError: Si el archivo no existe o no se puede leer.
        """
        path = Path(file_path)
        if not path.exists():
            raise MediaError(f"Archivo no encontrado: {file_path}")
        if not path.is_file():
            raise MediaError(f"No es un archivo válido: {file_path}")

        media_type = _detect_media_type(path)
        mime_type = _get_mime_type(path)
        size_bytes = path.stat().st_size

        metadata: Dict[str, Any] = {
            "filename": path.name,
            "extension": path.suffix.lower(),
            "created": path.stat().st_ctime,
            "modified": path.stat().st_mtime,
        }

        # Intentar extraer metadatos adicionales por tipo
        duration = None
        if media_type == MediaType.IMAGE:
            metadata.update(self._extract_image_metadata(path))
        elif media_type in (MediaType.AUDIO, MediaType.VIDEO):
            extra = self._extract_av_metadata(path)
            metadata.update(extra)
            duration = extra.get("duration_secs")

        media = MediaFile(
            path=path,
            media_type=media_type,
            mime_type=mime_type,
            size_bytes=size_bytes,
            duration_secs=duration,
            metadata=metadata,
        )
        logger.info(
            "Procesado %s: type=%s, mime=%s, size=%d",
            path.name, media_type.value, mime_type, size_bytes,
        )
        return media

    # ── Operaciones ─────────────────────────────────────────

    async def transcribe(self, media: MediaFile) -> str:
        """Transcribe audio/video a texto.

        Intenta en orden:
        1. OpenAI Whisper API (si OPENAI_API_KEY disponible)
        2. whisper CLI local (openai-whisper)
        3. Retorna mensaje de error
        """
        if media.media_type not in (MediaType.AUDIO, MediaType.VIDEO):
            raise MediaError(
                f"Transcripción no soportada para tipo {media.media_type.value}"
            )

        # 1. OpenAI Whisper API
        openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if openai_key:
            try:
                text = await self._transcribe_openai(media.path, openai_key)
                if text:
                    return text
            except Exception as exc:
                logger.warning("OpenAI Whisper API falló: %s", exc)

        # 2. whisper CLI local
        try:
            text = await self._transcribe_local_whisper(media.path)
            if text:
                return text
        except Exception as exc:
            logger.warning("whisper local falló: %s", exc)

        logger.warning("Transcripción no disponible. Configura OPENAI_API_KEY o instala whisper.")
        return "[Transcripción no disponible — configura OPENAI_API_KEY o instala openai-whisper]"

    async def _transcribe_openai(self, file_path: Path, api_key: str) -> str:
        """Transcribe usando la API de OpenAI Whisper (whisper-1).

        Args:
            file_path: Ruta al archivo de audio.
            api_key: API key de OpenAI.

        Returns:
            Texto transcrito o cadena vacía si falla.
        """
        import asyncio

        def _call_api() -> str:
            import urllib.request
            import json as _json

            boundary = f"----SomerBoundary{int(time.time() * 1000)}"
            body_parts: List[bytes] = []

            # Campo "model"
            body_parts.append(f"--{boundary}\r\n".encode())
            body_parts.append(
                b"Content-Disposition: form-data; name=\"model\"\r\n\r\nwhisper-1\r\n"
            )

            # Campo "file"
            filename = file_path.name
            mime = _get_mime_type(file_path)
            body_parts.append(f"--{boundary}\r\n".encode())
            body_parts.append(
                f"Content-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {mime}\r\n\r\n".encode()
            )
            body_parts.append(file_path.read_bytes())
            body_parts.append(b"\r\n")
            body_parts.append(f"--{boundary}--\r\n".encode())

            body = b"".join(body_parts)

            req = urllib.request.Request(
                "https://api.openai.com/v1/audio/transcriptions",
                data=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
                return data.get("text", "").strip()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _call_api)

    async def _transcribe_local_whisper(self, file_path: Path) -> str:
        """Transcribe usando whisper CLI local (openai-whisper)."""
        import asyncio

        def _run() -> str:
            import subprocess
            try:
                result = subprocess.run(
                    ["whisper", str(file_path), "--output_format", "txt",
                     "--output_dir", str(self._temp_dir)],
                    capture_output=True, text=True, timeout=300,
                )
                if result.returncode == 0:
                    txt_path = self._temp_dir / (file_path.stem + ".txt")
                    if txt_path.exists():
                        text = txt_path.read_text(encoding="utf-8").strip()
                        txt_path.unlink(missing_ok=True)
                        return text
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
            return ""

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _run)

    async def resize_image(
        self,
        media: MediaFile,
        max_width: int = 1280,
        max_height: int = 720,
    ) -> Path:
        """Redimensiona una imagen manteniendo aspecto.

        Requiere Pillow (PIL). Retorna la ruta del archivo redimensionado.
        """
        if media.media_type != MediaType.IMAGE:
            raise MediaError("Solo se pueden redimensionar imágenes")

        try:
            from PIL import Image
        except ImportError:
            raise MediaError("Pillow no instalado: pip install Pillow")

        img = Image.open(str(media.path))
        img.thumbnail((max_width, max_height), Image.LANCZOS)

        output_path = self._temp_dir / f"resized_{media.path.name}"
        img.save(str(output_path))
        logger.info("Imagen redimensionada: %s -> %s", media.path.name, output_path)
        return output_path

    async def extract_text(self, media: MediaFile) -> str:
        """Extrae texto de documentos PDF o imágenes (OCR).

        PDF: Usa PyPDF2/pypdf si está disponible.
        Imagen: Usa pytesseract si está disponible.
        """
        if media.media_type == MediaType.DOCUMENT and media.path.suffix.lower() == ".pdf":
            return self._extract_pdf_text(media.path)

        if media.media_type == MediaType.DOCUMENT and media.path.suffix.lower() == ".txt":
            return media.path.read_text(encoding="utf-8", errors="replace")

        if media.media_type == MediaType.IMAGE:
            return self._extract_ocr_text(media.path)

        raise MediaError(
            f"Extracción de texto no soportada para {media.mime_type}"
        )

    def cleanup_temp_files(self, max_age_secs: int = 3600) -> int:
        """Elimina archivos temporales más viejos que max_age_secs.

        Returns:
            Cantidad de archivos eliminados.
        """
        if not self._temp_dir.exists():
            return 0

        now = time.time()
        removed = 0
        for f in self._temp_dir.iterdir():
            if f.is_file():
                age = now - f.stat().st_mtime
                if age > max_age_secs:
                    f.unlink(missing_ok=True)
                    removed += 1

        if removed:
            logger.info("Limpiados %d archivos temporales de media", removed)
        return removed

    # ── Extracción de metadatos ─────────────────────────────

    @staticmethod
    def _extract_image_metadata(path: Path) -> Dict[str, Any]:
        """Extrae metadatos de imagen usando Pillow si está disponible."""
        try:
            from PIL import Image
            img = Image.open(str(path))
            return {
                "width": img.width,
                "height": img.height,
                "format": img.format or "unknown",
                "mode": img.mode,
            }
        except ImportError:
            return {}
        except Exception as exc:
            logger.debug("No se pudieron extraer metadatos de imagen: %s", exc)
            return {}

    @staticmethod
    def _extract_av_metadata(path: Path) -> Dict[str, Any]:
        """Extrae metadatos de audio/video usando ffprobe si está disponible."""
        try:
            import subprocess
            import json as _json
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", str(path)],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                data = _json.loads(result.stdout)
                fmt = data.get("format", {})
                duration = fmt.get("duration")
                return {
                    "duration_secs": float(duration) if duration else None,
                    "format_name": fmt.get("format_name", ""),
                    "bit_rate": fmt.get("bit_rate", ""),
                }
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        except Exception as exc:
            logger.debug("No se pudieron extraer metadatos A/V: %s", exc)
        return {}

    @staticmethod
    def _extract_pdf_text(path: Path) -> str:
        """Extrae texto de un PDF."""
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            pages: List[str] = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
            return "\n\n".join(pages)
        except ImportError:
            pass

        try:
            from PyPDF2 import PdfReader as PdfReader2
            reader2 = PdfReader2(str(path))
            pages2: List[str] = []
            for page in reader2.pages:
                text = page.extract_text()
                if text:
                    pages2.append(text)
            return "\n\n".join(pages2)
        except ImportError:
            raise MediaError("Instala pypdf o PyPDF2 para extraer texto de PDFs")

    @staticmethod
    def _extract_ocr_text(path: Path) -> str:
        """Extrae texto de una imagen usando OCR."""
        try:
            from PIL import Image
            import pytesseract
            img = Image.open(str(path))
            return pytesseract.image_to_string(img).strip()
        except ImportError:
            raise MediaError(
                "Instala Pillow y pytesseract para OCR: "
                "pip install Pillow pytesseract"
            )
