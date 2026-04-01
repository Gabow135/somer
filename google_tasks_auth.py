#!/usr/bin/env python3
"""
Google Tasks OAuth2 - localhost flow via SSH tunnel
Adds Tasks scope to existing Calendar credentials

Uso:
  python3 google_tasks_auth.py                      # usuario 'default'
  python3 google_tasks_auth.py --user-id 123456     # Telegram ID del usuario
  python3 google_tasks_auth.py --user-id esposa     # cualquier identificador

El token se guarda en:
  default  → ~/.somer/google_tasks_token.json   (compatibilidad legada)
  otros    → ~/.somer/google_tasks_token_{user_id}.json
"""
import json
import os
import sys
import urllib.request
import urllib.parse
import http.server
import threading
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/.somer/.env"))

CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
REDIRECT_URI = 'http://localhost:8080/callback'

# Determinar user_id desde argumentos de línea de comandos
_user_id = "default"
_args = sys.argv[1:]
if "--user-id" in _args:
    _idx = _args.index("--user-id")
    if _idx + 1 < len(_args):
        _user_id = _args[_idx + 1]
elif "--user" in _args:
    _idx = _args.index("--user")
    if _idx + 1 < len(_args):
        _user_id = _args[_idx + 1]

# Ruta del token: legada para 'default', con sufijo para otros usuarios
if _user_id == "default":
    TOKEN_FILE = os.path.expanduser('~/.somer/google_tasks_token.json')
else:
    TOKEN_FILE = os.path.expanduser(f'~/.somer/google_tasks_token_{_user_id}.json')

SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/tasks',
    'https://www.googleapis.com/auth/tasks.readonly',
]

auth_code = None
server_done = threading.Event()


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silenciar logs

    def do_GET(self):
        global auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if 'code' in params:
            auth_code = params['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'''
                <html><body style="font-family:sans-serif;text-align:center;padding:50px">
                <h2>&#10003; Autorizado correctamente</h2>
                <p>Puedes cerrar esta ventana.</p>
                </body></html>
            ''')
            server_done.set()
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'Error: no se recibi\xf3 el c\xf3digo')


def main():
    # Generar URL de autorización
    params = {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': ' '.join(SCOPES),
        'access_type': 'offline',
        'prompt': 'consent',
    }
    auth_url = 'https://accounts.google.com/o/oauth2/auth?' + urllib.parse.urlencode(params)

    print('\n' + '='*60)
    print(f'GOOGLE TASKS - AUTORIZACIÓN OAuth2  [usuario: {_user_id}]')
    print('='*60)
    print(f'\nToken se guardará en: {TOKEN_FILE}')
    print('\n1. Abre esta URL en tu navegador:\n')
    print(auth_url)
    print('\n2. Inicia sesión con la cuenta Google del usuario')
    print('3. El servidor capturará el código automáticamente')
    print('\nEsperando callback en puerto 8080...\n')

    # Iniciar servidor HTTP en background
    httpd = http.server.HTTPServer(('', 8080), CallbackHandler)
    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = True
    thread.start()

    # Esperar el callback (máx 5 minutos)
    server_done.wait(timeout=300)
    httpd.shutdown()

    if not auth_code:
        print('ERROR: No se recibió el código de autorización (timeout)')
        return

    print('Código recibido. Intercambiando por tokens...')

    # Intercambiar código por tokens
    data = urllib.parse.urlencode({
        'code': auth_code,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': REDIRECT_URI,
        'grant_type': 'authorization_code',
    }).encode()

    req = urllib.request.Request(
        'https://oauth2.googleapis.com/token',
        data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST'
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        tokens = json.loads(resp.read().decode())

    if 'error' in tokens:
        print(f'ERROR: {tokens}')
        return

    # Guardar token
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, 'w') as f:
        json.dump(tokens, f, indent=2)

    print(f'\n✓ Token guardado en {TOKEN_FILE}')
    print(f'  Usuario: {_user_id}')
    print(f'  Scopes: {tokens.get("scope", "N/A")}')
    print('\n¡Listo! Google Tasks conectado para este usuario.')


if __name__ == '__main__':
    main()
