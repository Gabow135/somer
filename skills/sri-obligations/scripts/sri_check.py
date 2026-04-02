#!/usr/bin/env python3
"""
SRI Ecuador — Consulta de Obligaciones Tributarias
Usa Playwright para login y extracción de datos.
"""

import argparse
import os
import sys
import json
import asyncio
from datetime import datetime
from pathlib import Path


def _load_dotenv():
    """Carga ~/.somer/.env si existe."""
    env_path = Path.home() / ".somer" / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key not in os.environ:
                        os.environ[key] = val

_load_dotenv()

# Credenciales: args posicionales tienen prioridad sobre env vars
def _parse_args():
    """Parsea argumentos CLI. Retorna namespace con ruc, password, name, use_json."""
    parser = argparse.ArgumentParser(description="SRI Ecuador — Consulta de Obligaciones")
    parser.add_argument("--ruc", default="", help="RUC del contribuyente (13 dígitos)")
    parser.add_argument("--password", default="", help="Password del portal SRI")
    parser.add_argument("--name", default="", help="Nombre o razón social del contribuyente (alternativa a --ruc para identificarlo)")
    parser.add_argument("--json", action="store_true", dest="use_json", help="Salida en formato JSON")
    args, _ = parser.parse_known_args()
    return args

_cli_args = _parse_args()

# Args CLI tienen prioridad; fallback a variables de entorno
SRI_RUC = _cli_args.ruc or os.environ.get("SRI_RUC", "")
SRI_PASSWORD = _cli_args.password or os.environ.get("SRI_PASSWORD", "")
SRI_NAME = _cli_args.name or os.environ.get("SRI_NAME", "")

SRI_URL = "https://srienlinea.sri.gob.ec/sri-en-linea/inicio/NAT"


async def consultar_obligaciones() -> dict:
    """Realiza login en SRI y extrae lista de obligaciones."""
    try:
        from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
    except ImportError:
        return {
            "success": False,
            "error": "Playwright no instalado. Ejecuta: pip install playwright && playwright install chromium",
            "obligaciones": []
        }

    if not SRI_RUC or not SRI_PASSWORD:
        return {
            "success": False,
            "error": "Credenciales no configuradas. Configura SRI_RUC y SRI_PASSWORD en ~/.somer/.env",
            "obligaciones": []
        }

    # Si se proporcionó --name pero no --ruc, intentar resolver desde la BD
    if not SRI_RUC and SRI_NAME:
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
            from agents.tools.sri_credentials import get_credentials_by_name
            matches = get_credentials_by_name(SRI_NAME)
            if matches:
                import os as _os
                _os.environ["SRI_RUC"] = matches[0]["ruc"]
        except Exception:
            pass

    async with async_playwright() as p:
        # Lanzar browser (headless por defecto)
        headless = os.environ.get("SRI_HEADLESS", "true").lower() != "false"
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            # 1. Navegar al sitio
            print(f"[SRI] Navegando a {SRI_URL}...", file=sys.stderr)
            await page.goto(SRI_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            # 2. Click en "Iniciar Sesión"
            print("[SRI] Buscando botón de login...", file=sys.stderr)
            login_btn = page.locator(".sri-tamano-link-iniciar-sesion").first
            await login_btn.wait_for(state="visible", timeout=15000)
            await login_btn.click()
            await page.wait_for_timeout(2000)

            # 3. Ingresar usuario (RUC/Cédula)
            print("[SRI] Ingresando credenciales...", file=sys.stderr)
            usuario_input = page.locator("#usuario")
            await usuario_input.wait_for(state="visible", timeout=15000)
            await usuario_input.fill(SRI_RUC)
            await page.wait_for_timeout(500)

            # 4. Ingresar password
            password_input = page.locator("#password")
            await password_input.wait_for(state="visible", timeout=10000)
            await password_input.fill(SRI_PASSWORD)
            await page.wait_for_timeout(500)

            # 5. Click en botón de login
            print("[SRI] Iniciando sesión...", file=sys.stderr)
            kc_login_btn = page.locator("#kc-login")
            await kc_login_btn.wait_for(state="visible", timeout=10000)
            await kc_login_btn.click()

            # Esperar carga del dashboard
            await page.wait_for_timeout(4000)
            await page.wait_for_load_state("domcontentloaded", timeout=20000)

            # 6. Verificar login exitoso
            current_url = page.url
            print(f"[SRI] URL post-login: {current_url}", file=sys.stderr)

            # Esperar a que aparezcan los panels
            await page.wait_for_timeout(3000)

            # 7. Extraer obligaciones de mat-expansion-panel-header-title
            print("[SRI] Extrayendo obligaciones...", file=sys.stderr)

            # Esperar que carguen los elementos
            try:
                await page.wait_for_selector(".mat-expansion-panel-header-title", timeout=15000)
            except PlaywrightTimeout:
                # Intentar capturar lo que hay en la página
                body_text = await page.inner_text("body")
                print(f"[SRI] No se encontraron panels. Contenido parcial: {body_text[:500]}", file=sys.stderr)

            obligaciones_elements = await page.locator(".mat-expansion-panel-header-title").all()

            obligaciones = []
            for elem in obligaciones_elements:
                try:
                    texto = await elem.inner_text()
                    texto = texto.strip()
                    if texto:
                        obligaciones.append(texto)
                except Exception:
                    pass

            # También intentar capturar textos dentro de los panels expandidos
            panel_descriptions = []
            try:
                desc_elements = await page.locator(".mat-expansion-panel-header-description").all()
                for elem in desc_elements:
                    texto = await elem.inner_text()
                    texto = texto.strip()
                    if texto:
                        panel_descriptions.append(texto)
            except Exception:
                pass

            # Intentar obtener más detalles si los panels tienen contenido adicional
            panel_details = []
            try:
                # Expandir todos los panels si hay pocos
                if len(obligaciones_elements) <= 10:
                    for elem in obligaciones_elements:
                        try:
                            await elem.click()
                            await page.wait_for_timeout(500)
                        except Exception:
                            pass

                    # Re-extraer después de expandir
                    panel_body_elements = await page.locator(".mat-expansion-panel-body").all()
                    for elem in panel_body_elements:
                        try:
                            texto = await elem.inner_text()
                            texto = texto.strip()
                            if texto:
                                panel_details.append(texto)
                        except Exception:
                            pass
            except Exception:
                pass

            return {
                "success": True,
                "ruc": SRI_RUC,
                "name": SRI_NAME or None,
                "timestamp": datetime.now().isoformat(),
                "obligaciones": obligaciones,
                "descripciones": panel_descriptions,
                "detalles": panel_details,
                "total": len(obligaciones),
                "url": current_url
            }

        except PlaywrightTimeout as e:
            return {
                "success": False,
                "error": f"Timeout: {str(e)}",
                "obligaciones": []
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "obligaciones": []
            }
        finally:
            await context.close()
            await browser.close()


def format_output(result: dict) -> str:
    """Formatea el resultado en template TPL-ACTION de SOMER."""
    from datetime import date
    today = date.today().strftime("%d/%b/%Y")

    if not result["success"]:
        return f"""ACCIÓN — SRI Ecuador | Error | {today}

RESULTADO
  Estado:     Error
  Detalle:    {result['error']}

---
Ejecutado por: SOMER SRI Obligations"""

    obligaciones = result.get("obligaciones", [])
    descripciones = result.get("descripciones", [])
    detalles = result.get("detalles", [])
    total = result.get("total", 0)

    ruc_val = result.get('ruc', 'N/A')
    name_val = result.get('name') or ""
    lines = [
        f"ACCIÓN — SRI Ecuador | Obligaciones | {today}",
        "",
        "RESULTADO",
        f"  Estado:     Completado",
        f"  RUC:        {ruc_val}",
    ]
    if name_val:
        lines.append(f"  Nombre:     {name_val}")
    lines.extend([
        f"  Total:      {total} obligaciones encontradas",
        ""
    ])

    if obligaciones:
        lines.append("OBLIGACIONES")
        for i, obl in enumerate(obligaciones, 1):
            # Combinar con descripción si existe
            desc = descripciones[i-1] if i-1 < len(descripciones) else ""
            if desc:
                lines.append(f"  {i:2}. {obl}")
                lines.append(f"      └─ {desc}")
            else:
                lines.append(f"  {i:2}. {obl}")
        lines.append("")

    if detalles:
        lines.append("DETALLES ADICIONALES")
        for det in detalles[:5]:  # Limitar a 5 para no saturar
            # Truncar si es muy largo
            det_short = det[:200] + "..." if len(det) > 200 else det
            lines.append(f"  {det_short}")
        lines.append("")

    if not obligaciones:
        lines.append("  [OK] Sin obligaciones pendientes encontradas")
        lines.append("")

    lines.extend([
        "---",
        f"Fuente: SRI Ecuador | srienlinea.sri.gob.ec | {result.get('timestamp', '')[:10]}"
    ])

    return "\n".join(lines)


def _notificar_whatsapp_obligaciones(result: dict) -> None:
    """Envía notificación WhatsApp si el RUC tiene obligaciones y número configurado.

    Consulta el número WhatsApp del RUC en sri_credentials.db. Si no tiene número
    configurado, solo registra un warning y continúa sin fallar.

    Args:
        result: Resultado de consultar_obligaciones() con claves success, ruc, obligaciones, etc.
    """
    if not result.get("success"):
        return

    obligaciones = result.get("obligaciones", [])
    if not obligaciones:
        return  # Sin obligaciones pendientes, no hay nada que notificar

    ruc = result.get("ruc", "")
    nombre = result.get("name", "") or ""

    if not ruc:
        return

    # Resolver número WhatsApp desde la BD de credenciales SRI
    whatsapp_number: str | None = None
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
        from channels.whatsapp.notifier import WhatsAppNotifier
        from agents.tools.sri_credentials import get_credentials

        creds = get_credentials(ruc)
        if creds:
            whatsapp_number = creds.get("whatsapp_number")
    except Exception as exc:
        print(f"[SRI] Advertencia: no se pudo cargar notifier WhatsApp: {exc}", file=sys.stderr)
        return

    if not whatsapp_number:
        print(
            f"[SRI] Advertencia: RUC {ruc} no tiene whatsapp_number configurado — "
            "notificación WhatsApp omitida",
            file=sys.stderr,
        )
        return

    # Construir resumen de obligaciones para el mensaje
    total = len(obligaciones)
    # Incluir las primeras 3 obligaciones más urgentes en el mensaje
    primeras = obligaciones[:3]
    resumen_items = "; ".join(primeras)
    if total > 3:
        resumen_items += f" (y {total - 3} más)"
    mensaje = f"{total} obligación(es) pendiente(s): {resumen_items}"

    razonsocial = nombre or ruc

    try:
        notifier = WhatsAppNotifier()
        resultado_wa = notifier.notify_sri_obligation(
            whatsapp_number=whatsapp_number,
            ruc=ruc,
            razonsocial=razonsocial,
            obligation_detail=mensaje,
        )
        if resultado_wa.get("success"):
            print(
                f"[SRI] Notificación WhatsApp enviada a {whatsapp_number} para RUC {ruc}",
                file=sys.stderr,
            )
        else:
            print(
                f"[SRI] Advertencia: fallo al enviar WhatsApp a {whatsapp_number}: "
                f"{resultado_wa.get('error', 'error desconocido')}",
                file=sys.stderr,
            )
    except Exception as exc:
        print(f"[SRI] Advertencia: error inesperado enviando WhatsApp: {exc}", file=sys.stderr)


async def main():
    result = await consultar_obligaciones()

    # Enviar notificación WhatsApp si hay obligaciones pendientes
    _notificar_whatsapp_obligaciones(result)

    # Output JSON si se pide (--json flag o detección legacy)
    if _cli_args.use_json or "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_output(result))

    # Exit code
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    asyncio.run(main())
