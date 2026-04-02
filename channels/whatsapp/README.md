# Canal WhatsApp — SOMER 2.0

Integración con **WhatsApp Business Cloud API** (Meta Graph API v20.0).
Permite enviar y recibir mensajes desde el gateway SOMER usando la infraestructura
de Meta sin depender de proveedores intermediarios.

---

## Estructura del módulo

```
channels/whatsapp/
├── __init__.py          — Exports públicos del canal
├── plugin.py            — Plugin de canal para el gateway SOMER
├── client.py            — Cliente HTTP hacia la Graph API de Meta
├── sender.py            — Funciones síncronas y clase async de envío
├── webhook.py           — WhatsAppWebhook (verificación/parseo) + WhatsAppWebhookServer
├── handler.py           — Procesador de mensajes entrantes con integración SRI
├── server.py            — Servidor HTTP standalone (aiohttp, puerto 8080)
├── notifier.py          — Dispatcher de notificaciones para usuarios SRI
└── send_notification.py — Script standalone para envíos desde CLI
```

---

## Variables de entorno requeridas

Agrega estas variables a `~/.somer/.env`:

```env
# Token de acceso de la Meta App (permanente o de larga duración)
WHATSAPP_ACCESS_TOKEN=EAAxxxxxxxxxx...

# ID del número de teléfono de negocio registrado en Meta
WHATSAPP_PHONE_NUMBER_ID=1234567890

# Token secreto para verificar el webhook (lo defines tú, no Meta)
# Debe coincidir exactamente con el que configures en Meta Developers
WHATSAPP_VERIFY_TOKEN=mi_token_secreto_webhook
```

### Variables opcionales

```env
# Versión de la Graph API (default: v20.0)
WHATSAPP_API_VERSION=v20.0

# Alias heredado del token (retrocompatibilidad)
WHATSAPP_TOKEN=EAAxxxxxxxxxx...

# Configuración del servidor webhook standalone
WHATSAPP_WEBHOOK_PORT=8080        # Puerto del servidor (default: 8080)
WHATSAPP_WEBHOOK_HOST=0.0.0.0     # Host del servidor (default: 0.0.0.0)
WHATSAPP_WEBHOOK_PATH=/webhook    # Ruta del endpoint (default: /webhook)
```

> **Importante:** Nunca hardcodees tokens en el código fuente.
> Usa siempre variables de entorno o el `CredentialStore` de SOMER.

### Generar un token de verificación seguro

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# Ejemplo de salida: kX4nVB2hPq8mR7wZ...
```

Copia el valor generado y agrégalo a `~/.somer/.env`:

```bash
echo "WHATSAPP_VERIFY_TOKEN=pega_aqui_el_token_generado" >> ~/.somer/.env
```

---

## Configurar el webhook en Meta Developers

### Paso a paso

1. Ve a [developers.facebook.com](https://developers.facebook.com) e inicia sesión.
2. Abre tu aplicación de Meta (o crea una nueva de tipo "Business").
3. En el menú lateral, selecciona **WhatsApp → Configuración**.
4. En la sección **Webhooks**, haz clic en **Editar**.
5. Completa los campos:
   - **URL del webhook**: `https://tu-dominio.com/webhook`
     (debe ser **HTTPS** con certificado válido y accesible desde internet)
   - **Token de verificación**: el mismo valor de `WHATSAPP_VERIFY_TOKEN`
6. Haz clic en **Verificar y guardar**.
   - Meta enviará un `GET /webhook?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...`
   - Tu servidor responderá con el valor de `hub.challenge` para confirmar la propiedad.
7. En la sección **Campos de webhook**, suscríbete al campo **messages**.
   Esto habilita la recepción de mensajes entrantes, estados de entrega, etc.

### URL del webhook

La URL que debes registrar en Meta es:

```
https://tu-dominio.com/webhook
```

Reemplaza `tu-dominio.com` con el dominio real donde está expuesto el servidor.
El servidor debe escuchar en el puerto 443 (HTTPS) o detrás de un reverse proxy
(nginx, Caddy, etc.) que maneje el TLS.

### Campos a habilitar en Meta Developers

| Campo     | Descripción                                               |
|-----------|-----------------------------------------------------------|
| `messages`| Mensajes entrantes, estados de entrega y reacciones       |

Los demás campos son opcionales según las funcionalidades que necesites.

---

## Levantar el servidor webhook

### Opción 1: Script de arranque (recomendado)

```bash
# Desde la raíz del proyecto SOMER
./scripts/start_whatsapp_webhook.sh

# Con modo debug (más logs)
./scripts/start_whatsapp_webhook.sh --debug

# En puerto personalizado
./scripts/start_whatsapp_webhook.sh --port 9090
```

El script:
- Carga automáticamente `~/.somer/.env`
- Verifica que aiohttp esté instalado (lo instala si falta)
- Muestra la configuración antes de iniciar
- Imprime la URL a registrar en Meta

### Opción 2: Directamente como módulo Python

```bash
# Desde la raíz del proyecto
PYTHONPATH=. python3 -m channels.whatsapp.server
```

### Opción 3: Programáticamente desde Python

```python
import asyncio
from channels.whatsapp.server import WhatsAppServer

async def main():
    servidor = WhatsAppServer(
        port=8080,
        host="0.0.0.0",
        webhook_path="/webhook",
    )
    await servidor.start()
    # El servidor ya está escuchando
    await asyncio.sleep(3600)  # Mantener activo
    await servidor.stop()

asyncio.run(main())
```

### Opción 4: Integrado en el gateway SOMER

El `WhatsAppPlugin` en `plugin.py` levanta automáticamente el servidor de webhook
cuando se inicia el gateway SOMER mediante `somer gateway start`.

---

## Desarrollo local con ngrok

Para exponer el puerto local a internet durante el desarrollo:

```bash
# Instalar ngrok (https://ngrok.com)
# Iniciar el servidor SOMER en puerto 8080
./scripts/start_whatsapp_webhook.sh --port 8080

# En otra terminal, exponer con ngrok
ngrok http 8080
```

ngrok mostrará una URL pública HTTPS como `https://abc123.ngrok.io`.
Registra en Meta Developers:

```
https://abc123.ngrok.io/webhook
```

---

## Procesamiento de mensajes entrantes

### Comandos automáticos

El `WhatsAppMessageHandler` responde automáticamente a estos comandos:

| Mensaje enviado       | Respuesta automática                           |
|-----------------------|------------------------------------------------|
| `AYUDA` / `HELP`      | Instrucciones de uso y comandos disponibles    |
| `ESTADO` / `STATUS`   | Estado del sistema SOMER y usuario identificado|
| `INFO` / `HOLA`       | Saludo y presentación de SOMER                 |

### Cola de mensajes para el agente

Los mensajes que no son comandos simples se encolan en la cola asyncio
para que el agente SOMER los procese:

```python
from channels.whatsapp import get_incoming_queue

cola = get_incoming_queue()

# Consumir mensajes pendientes
while not cola.empty():
    mensaje = await cola.get()
    print(f"De: {mensaje['from_number']}")
    print(f"Texto: {mensaje['text']}")
    print(f"Usuario SRI: {mensaje['usuario_sri']}")
```

Cada entrada en la cola tiene esta estructura:

```python
{
    "from_number":    "593987654321",     # Número del remitente
    "contact_name":   "Juan Pérez",       # Nombre del contacto (si disponible)
    "message_id":     "wamid.xxx",        # ID del mensaje de Meta
    "message_type":   "text",             # text, image, audio, video, etc.
    "text":           "Hola!",            # Texto extraído del mensaje
    "timestamp":      "1712345678",       # Unix timestamp
    "phone_number_id":"123456",           # ID del número receptor (tu número)
    "usuario_sri":    {                   # None si no está en sri_credentials.db
        "ruc":            "1791234560001",
        "name":           "Empresa SA",
        "alias":          "empresa_sa",
        "whatsapp_number":"593987654321",
    },
    "raw":            {...},              # Mensaje original completo de Meta
}
```

### Integración con usuarios SRI

El handler busca automáticamente en `~/.somer/sri_credentials.db` si el número
del remitente pertenece a un usuario registrado. El resultado se incluye en la
entrada de la cola como `usuario_sri`.

---

## Envío de mensajes

### Texto simple

```python
from channels.whatsapp import send_text

resultado = send_text("593987654321", "Hola! Este es un mensaje de prueba.")
print(resultado)
# {"http_code": 200, "response": {...}, "success": True}
```

### Template dtirols

```python
from channels.whatsapp import send_template_dtirols

resultado = send_template_dtirols(
    celular="593987654321",
    razonsocial="Empresa S.A.",
    body_text="Su declaración de IVA vence el 10/04/2026.",
)
```

### Template genérico con componentes

```python
from channels.whatsapp import send_template

resultado = send_template(
    celular="593987654321",
    template_name="mi_template",
    language_code="es_EC",
    components=[
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": "Juan"},
                {"type": "text", "text": "500.00"},
            ],
        }
    ],
)
```

### Media (imagen, video, documento)

```python
from channels.whatsapp import send_media

send_media(
    celular="593987654321",
    media_type="document",
    media_url="https://ejemplo.com/factura.pdf",
    caption="Factura #1234",
)
```

### Usando la clase async `WhatsAppSender`

```python
import asyncio
from channels.whatsapp import WhatsAppSender

async def main():
    sender = WhatsAppSender()
    await sender.send_text("593987654321", "Hola desde SOMER!")
    await sender.send_template_dtirols(
        celular="593987654321",
        razonsocial="Empresa S.A.",
        body_text="Su solicitud fue aprobada.",
    )

asyncio.run(main())
```

---

## Notificaciones proactivas

```python
from channels.whatsapp import WhatsAppNotifier

notifier = WhatsAppNotifier()

# Notificar un usuario específico
notifier.notify_user("593987654321", "Su declaración vence mañana", "Empresa SA")

# Notificar por obligación SRI
notifier.notify_sri_obligation(
    whatsapp_number="593987654321",
    ruc="1791234560001",
    razonsocial="Empresa SA",
    obligation_detail="IVA mensual vence 10/04/2026",
)

# Notificar a todos los usuarios SRI con WhatsApp configurado
resultados = notifier.notify_all_sri_users("Recordatorio: vence declaración IVA")
for r in resultados:
    print(r)
```

---

## Script standalone de envío

```bash
# Cargar variables de entorno
source ~/.somer/.env

# Enviar template dtirols desde la CLI
python3 channels/whatsapp/send_notification.py \
    +593987654321 \
    "Empresa S.A." \
    "Su rol de pagos está listo para su firma"
```

---

## Requisitos técnicos del servidor webhook

- URL pública con **HTTPS** (certificado SSL válido — Meta rechaza HTTP).
- Responder al `GET` de verificación con el `hub.challenge` exacto.
- Responder `HTTP 200 OK` al `POST` en menos de **5 segundos**.
  El procesamiento real se realiza en background con `asyncio.create_task`.
- El servidor debe estar accesible desde las IPs de Meta (no filtrar por IP).

---

## Dependencias

El servidor usa `aiohttp` (no incluido en las dependencias base de SOMER).
Instalación:

```bash
pip install aiohttp
```

O instalar todas las dependencias del proyecto:

```bash
pip install -e ".[all]"
```
