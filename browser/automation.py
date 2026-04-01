"""Browser automation usando Playwright — navegación, capturas, interacción."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.constants import DEFAULT_HOME
from shared.errors import SomerError

logger = logging.getLogger(__name__)

PROFILES_DIR = DEFAULT_HOME / "browser_profiles"


class BrowserError(SomerError):
    """Error en automatización del navegador."""


@dataclass
class BrowserProfile:
    """Perfil de navegador aislado con su propio storage."""

    name: str
    user_data_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.user_data_dir = PROFILES_DIR / self.name
        self.user_data_dir.mkdir(parents=True, exist_ok=True)


class BrowserManager:
    """Gestor de navegador headless con Playwright.

    Importa playwright lazily en ``launch()`` para no requerir
    la dependencia si el módulo no se usa.

    Uso típico::

        mgr = BrowserManager(profile="default", headless=True)
        await mgr.launch()
        await mgr.navigate("https://example.com")
        text = await mgr.get_text()
        await mgr.close()
    """

    def __init__(
        self,
        profile: str = "default",
        headless: bool = True,
        timeout_ms: int = 30_000,
    ) -> None:
        self._profile = BrowserProfile(name=profile)
        self._headless = headless
        self._timeout_ms = timeout_ms

        # Inicializados en launch()
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

    # ── Lifecycle ───────────────────────────────────────────

    async def launch(self) -> None:
        """Lanza el navegador con el perfil configurado."""
        if self._browser is not None:
            logger.warning("El navegador ya está iniciado")
            return

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise BrowserError(
                "playwright no está instalado. "
                "Ejecuta: pip install playwright && playwright install chromium"
            )

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self._profile.user_data_dir),
            headless=self._headless,
        )
        # Usar la primera página o crear una nueva
        pages = self._browser.pages
        self._page = pages[0] if pages else await self._browser.new_page()
        self._page.set_default_timeout(self._timeout_ms)
        logger.info("Navegador lanzado con perfil '%s'", self._profile.name)

    async def close(self) -> None:
        """Cierra el navegador y libera recursos."""
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
            self._page = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        logger.info("Navegador cerrado")

    def _ensure_page(self) -> Any:
        """Valida que hay una página activa."""
        if self._page is None:
            raise BrowserError("Navegador no iniciado. Llama a launch() primero.")
        return self._page

    # ── Navegación ──────────────────────────────────────────

    async def navigate(self, url: str, wait_until: str = "domcontentloaded") -> str:
        """Navega a una URL y devuelve el título de la página."""
        page = self._ensure_page()
        response = await page.goto(url, wait_until=wait_until)
        status = response.status if response else 0
        title = await page.title()
        logger.info("Navegado a %s (status=%d, title='%s')", url, status, title)
        return title

    async def get_text(self, selector: Optional[str] = None) -> str:
        """Obtiene el texto visible de la página o de un selector."""
        page = self._ensure_page()
        if selector:
            element = await page.query_selector(selector)
            if element is None:
                raise BrowserError(f"Selector no encontrado: {selector}")
            return (await element.inner_text()).strip()
        return (await page.inner_text("body")).strip()

    async def screenshot(
        self,
        path: Optional[str] = None,
        full_page: bool = False,
        selector: Optional[str] = None,
    ) -> Path:
        """Captura screenshot y devuelve la ruta del archivo."""
        page = self._ensure_page()
        if path is None:
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            path = tmp.name
            tmp.close()

        if selector:
            element = await page.query_selector(selector)
            if element is None:
                raise BrowserError(f"Selector no encontrado: {selector}")
            await element.screenshot(path=path)
        else:
            await page.screenshot(path=path, full_page=full_page)

        logger.info("Screenshot guardado en %s", path)
        return Path(path)

    # ── Interacción ─────────────────────────────────────────

    async def click(self, selector: str) -> None:
        """Hace click en un elemento."""
        page = self._ensure_page()
        await page.click(selector)
        logger.debug("Click en '%s'", selector)

    async def type_text(
        self, selector: str, text: str, *, delay: int = 50
    ) -> None:
        """Escribe texto en un campo de entrada."""
        page = self._ensure_page()
        await page.fill(selector, "")
        await page.type(selector, text, delay=delay)
        logger.debug("Texto escrito en '%s'", selector)

    async def evaluate(self, js: str) -> Any:
        """Ejecuta JavaScript en la página y devuelve el resultado."""
        page = self._ensure_page()
        result = await page.evaluate(js)
        return result

    # ── Utilidades ──────────────────────────────────────────

    async def wait_for(self, selector: str, state: str = "visible") -> None:
        """Espera a que un elemento alcance un estado dado."""
        page = self._ensure_page()
        await page.wait_for_selector(selector, state=state)

    @property
    def current_url(self) -> str:
        """URL actual de la página."""
        page = self._ensure_page()
        return page.url

    @staticmethod
    def list_profiles() -> List[str]:
        """Devuelve los nombres de perfiles disponibles."""
        if not PROFILES_DIR.exists():
            return []
        return [p.name for p in PROFILES_DIR.iterdir() if p.is_dir()]
