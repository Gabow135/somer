"""Base de remediaciones con snippets de código real por plataforma.

Cada entrada mapea un check_id a una RemediationGuide con:
- Explicación de por qué importa
- Snippets de configuración por plataforma (nginx, Apache, Express, etc.)
- Referencias a OWASP, MDN, etc.
"""

from __future__ import annotations

from typing import List, Optional

from cybersecurity.types import CodeSnippet, Finding, RemediationGuide


# ── REMEDIATION_DB ───────────────────────────────────────────

REMEDIATION_DB: List[RemediationGuide] = [
    # ── Headers de seguridad ─────────────────────────────────
    RemediationGuide(
        check_id="missing_csp",
        title="Content Security Policy (CSP)",
        explanation=(
            "CSP previene ataques XSS y de inyección limitando qué orígenes "
            "pueden cargar scripts, estilos e imágenes en tu sitio."
        ),
        snippets=[
            CodeSnippet(
                platform="nginx",
                language="nginx",
                description="Agregar CSP en nginx.conf o server block",
                code='add_header Content-Security-Policy "default-src \'self\'; script-src \'self\'; style-src \'self\' \'unsafe-inline\'; img-src \'self\' data:; font-src \'self\'" always;',
            ),
            CodeSnippet(
                platform="apache",
                language="apache",
                description="Agregar CSP en .htaccess o httpd.conf",
                code='Header always set Content-Security-Policy "default-src \'self\'; script-src \'self\'; style-src \'self\' \'unsafe-inline\'; img-src \'self\' data:; font-src \'self\'"',
            ),
            CodeSnippet(
                platform="express",
                language="javascript",
                description="Usar helmet para CSP en Express/Node.js",
                code="""\
const helmet = require('helmet');

app.use(helmet.contentSecurityPolicy({
  directives: {
    defaultSrc: ["'self'"],
    scriptSrc: ["'self'"],
    styleSrc: ["'self'", "'unsafe-inline'"],
    imgSrc: ["'self'", "data:"],
    fontSrc: ["'self'"],
  },
}));""",
            ),
            CodeSnippet(
                platform="nextjs",
                language="javascript",
                description="CSP en next.config.js con headers",
                code="""\
// next.config.js
module.exports = {
  async headers() {
    return [{
      source: '/(.*)',
      headers: [{
        key: 'Content-Security-Policy',
        value: "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'",
      }],
    }];
  },
};""",
            ),
        ],
        references=[
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP",
            "https://owasp.org/www-project-secure-headers/#content-security-policy",
        ],
    ),
    RemediationGuide(
        check_id="missing_hsts",
        title="HTTP Strict Transport Security (HSTS)",
        explanation=(
            "HSTS fuerza a los navegadores a usar HTTPS, previniendo ataques "
            "de downgrade y cookie hijacking por HTTP."
        ),
        snippets=[
            CodeSnippet(
                platform="nginx",
                language="nginx",
                description="HSTS en nginx (1 year, includeSubDomains)",
                code='add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;',
            ),
            CodeSnippet(
                platform="apache",
                language="apache",
                description="HSTS en Apache .htaccess",
                code='Header always set Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"',
            ),
            CodeSnippet(
                platform="express",
                language="javascript",
                description="HSTS con helmet en Express",
                code="""\
const helmet = require('helmet');
app.use(helmet.hsts({
  maxAge: 31536000,
  includeSubDomains: true,
  preload: true,
}));""",
            ),
            CodeSnippet(
                platform="nextjs",
                language="javascript",
                description="HSTS en next.config.js",
                code="""\
// next.config.js
module.exports = {
  async headers() {
    return [{
      source: '/(.*)',
      headers: [{
        key: 'Strict-Transport-Security',
        value: 'max-age=31536000; includeSubDomains; preload',
      }],
    }];
  },
};""",
            ),
        ],
        references=[
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Strict-Transport-Security",
            "https://hstspreload.org/",
        ],
    ),
    RemediationGuide(
        check_id="missing_x_frame_options",
        title="X-Frame-Options",
        explanation=(
            "Previene que tu sitio sea embebido en iframes de otros dominios, "
            "protegiendo contra clickjacking."
        ),
        snippets=[
            CodeSnippet(
                platform="nginx",
                language="nginx",
                description="X-Frame-Options en nginx",
                code='add_header X-Frame-Options "DENY" always;',
            ),
            CodeSnippet(
                platform="apache",
                language="apache",
                description="X-Frame-Options en Apache",
                code='Header always set X-Frame-Options "DENY"',
            ),
            CodeSnippet(
                platform="express",
                language="javascript",
                description="X-Frame-Options con helmet",
                code="app.use(helmet.frameguard({ action: 'deny' }));",
            ),
        ],
        references=[
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Frame-Options",
            "https://owasp.org/www-community/attacks/Clickjacking",
        ],
    ),
    RemediationGuide(
        check_id="missing_x_content_type",
        title="X-Content-Type-Options",
        explanation=(
            "Previene MIME type sniffing que puede convertir archivos no ejecutables "
            "en scripts ejecutables."
        ),
        snippets=[
            CodeSnippet(
                platform="nginx",
                language="nginx",
                description="X-Content-Type-Options en nginx",
                code='add_header X-Content-Type-Options "nosniff" always;',
            ),
            CodeSnippet(
                platform="apache",
                language="apache",
                description="X-Content-Type-Options en Apache",
                code='Header always set X-Content-Type-Options "nosniff"',
            ),
            CodeSnippet(
                platform="express",
                language="javascript",
                description="X-Content-Type-Options con helmet",
                code="app.use(helmet.noSniff());",
            ),
        ],
        references=[
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Content-Type-Options",
        ],
    ),
    RemediationGuide(
        check_id="missing_referrer_policy",
        title="Referrer-Policy",
        explanation=(
            "Controla cuánta información del referrer se envía al navegar "
            "entre páginas, previniendo fugas de datos sensibles en URLs."
        ),
        snippets=[
            CodeSnippet(
                platform="nginx",
                language="nginx",
                description="Referrer-Policy en nginx",
                code='add_header Referrer-Policy "strict-origin-when-cross-origin" always;',
            ),
            CodeSnippet(
                platform="apache",
                language="apache",
                description="Referrer-Policy en Apache",
                code='Header always set Referrer-Policy "strict-origin-when-cross-origin"',
            ),
            CodeSnippet(
                platform="express",
                language="javascript",
                description="Referrer-Policy con helmet",
                code="app.use(helmet.referrerPolicy({ policy: 'strict-origin-when-cross-origin' }));",
            ),
        ],
        references=[
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Referrer-Policy",
        ],
    ),
    RemediationGuide(
        check_id="missing_permissions_policy",
        title="Permissions-Policy",
        explanation=(
            "Controla qué APIs del navegador (cámara, micrófono, geolocalización) "
            "puede usar tu sitio y los iframes embebidos."
        ),
        snippets=[
            CodeSnippet(
                platform="nginx",
                language="nginx",
                description="Permissions-Policy en nginx",
                code='add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;',
            ),
            CodeSnippet(
                platform="apache",
                language="apache",
                description="Permissions-Policy en Apache",
                code='Header always set Permissions-Policy "camera=(), microphone=(), geolocation=()"',
            ),
            CodeSnippet(
                platform="express",
                language="javascript",
                description="Permissions-Policy con helmet",
                code="""\
app.use(helmet.permittedCrossDomainPolicies());
app.use((req, res, next) => {
  res.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
  next();
});""",
            ),
        ],
        references=[
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Permissions-Policy",
        ],
    ),
    RemediationGuide(
        check_id="server_info_disclosure",
        title="Divulgación de información del servidor",
        explanation=(
            "Headers como Server y X-Powered-By revelan software y versiones, "
            "facilitando ataques dirigidos a vulnerabilidades conocidas."
        ),
        snippets=[
            CodeSnippet(
                platform="nginx",
                language="nginx",
                description="Ocultar versión en nginx",
                code="server_tokens off;",
            ),
            CodeSnippet(
                platform="apache",
                language="apache",
                description="Ocultar versión en Apache",
                code="ServerTokens Prod\nServerSignature Off",
            ),
        ],
        references=[
            "https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/01-Information_Gathering/02-Fingerprint_Web_Server",
        ],
    ),
    # ── Cookies ──────────────────────────────────────────────
    RemediationGuide(
        check_id="cookie_no_secure",
        title="Cookie sin flag Secure",
        explanation=(
            "Sin el flag Secure, las cookies se transmiten por HTTP sin cifrar, "
            "permitiendo interceptación en redes inseguras."
        ),
        snippets=[
            CodeSnippet(
                platform="express",
                language="javascript",
                description="Cookie segura en Express",
                code="""\
app.use(session({
  cookie: {
    secure: true,
    httpOnly: true,
    sameSite: 'lax',
    maxAge: 24 * 60 * 60 * 1000,
  },
}));""",
            ),
            CodeSnippet(
                platform="django",
                language="python",
                description="Cookie segura en Django settings.py",
                code="""\
# settings.py
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True""",
            ),
        ],
        references=[
            "https://owasp.org/www-community/controls/SecureCookieAttribute",
        ],
    ),
    RemediationGuide(
        check_id="cookie_no_httponly",
        title="Cookie sin flag HttpOnly",
        explanation=(
            "Sin HttpOnly, JavaScript puede acceder a la cookie vía document.cookie, "
            "facilitando robo de sesión mediante XSS."
        ),
        snippets=[
            CodeSnippet(
                platform="express",
                language="javascript",
                description="HttpOnly en Express",
                code="app.use(session({ cookie: { httpOnly: true } }));",
            ),
            CodeSnippet(
                platform="django",
                language="python",
                description="HttpOnly en Django",
                code="SESSION_COOKIE_HTTPONLY = True  # Es True por defecto en Django",
            ),
        ],
        references=[
            "https://owasp.org/www-community/HttpOnly",
        ],
    ),
    RemediationGuide(
        check_id="cookie_no_samesite",
        title="Cookie sin SameSite",
        explanation=(
            "SameSite previene que la cookie se envíe en requests cross-site, "
            "protegiendo contra CSRF."
        ),
        snippets=[
            CodeSnippet(
                platform="express",
                language="javascript",
                description="SameSite en Express",
                code="app.use(session({ cookie: { sameSite: 'lax' } }));",
            ),
            CodeSnippet(
                platform="django",
                language="python",
                description="SameSite en Django",
                code='SESSION_COOKIE_SAMESITE = "Lax"',
            ),
        ],
        references=[
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Set-Cookie/SameSite",
        ],
    ),
    # ── SSL/TLS ──────────────────────────────────────────────
    RemediationGuide(
        check_id="ssl_expires_soon",
        title="Certificado SSL próximo a expirar",
        explanation=(
            "Un certificado expirado causa errores en los navegadores y puede "
            "interrumpir completamente el acceso al sitio."
        ),
        snippets=[
            CodeSnippet(
                platform="general",
                language="bash",
                description="Renovar con Certbot (Let's Encrypt)",
                code="sudo certbot renew --dry-run\nsudo certbot renew",
            ),
            CodeSnippet(
                platform="general",
                language="bash",
                description="Cron job para renovación automática",
                code="0 0 1 * * /usr/bin/certbot renew --quiet --post-hook 'systemctl reload nginx'",
            ),
        ],
        references=[
            "https://letsencrypt.org/docs/",
            "https://certbot.eff.org/",
        ],
    ),
    RemediationGuide(
        check_id="ssl_weak_protocol",
        title="Protocolo TLS débil",
        explanation=(
            "SSLv3, TLS 1.0 y TLS 1.1 tienen vulnerabilidades conocidas (POODLE, BEAST). "
            "Solo TLS 1.2+ es considerado seguro."
        ),
        snippets=[
            CodeSnippet(
                platform="nginx",
                language="nginx",
                description="Solo TLS 1.2+ en nginx",
                code="ssl_protocols TLSv1.2 TLSv1.3;\nssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;\nssl_prefer_server_ciphers off;",
            ),
            CodeSnippet(
                platform="apache",
                language="apache",
                description="Solo TLS 1.2+ en Apache",
                code="SSLProtocol all -SSLv2 -SSLv3 -TLSv1 -TLSv1.1\nSSLCipherSuite ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256\nSSLHonorCipherOrder off",
            ),
        ],
        references=[
            "https://ssl-config.mozilla.org/",
        ],
    ),
    # ── CORS ─────────────────────────────────────────────────
    RemediationGuide(
        check_id="cors_wildcard",
        title="CORS con wildcard",
        explanation=(
            "Access-Control-Allow-Origin: * permite que cualquier sitio acceda "
            "a tus recursos, lo cual es peligroso si hay datos sensibles."
        ),
        snippets=[
            CodeSnippet(
                platform="express",
                language="javascript",
                description="CORS con whitelist en Express",
                code="""\
const cors = require('cors');
const allowedOrigins = ['https://app.example.com', 'https://admin.example.com'];

app.use(cors({
  origin: (origin, callback) => {
    if (!origin || allowedOrigins.includes(origin)) {
      callback(null, true);
    } else {
      callback(new Error('No permitido por CORS'));
    }
  },
  credentials: true,
}));""",
            ),
            CodeSnippet(
                platform="nginx",
                language="nginx",
                description="CORS con origin check en nginx",
                code="""\
set $cors_origin "";
if ($http_origin ~* "^https://(app|admin)\\.example\\.com$") {
    set $cors_origin $http_origin;
}
add_header Access-Control-Allow-Origin $cors_origin always;
add_header Access-Control-Allow-Credentials "true" always;""",
            ),
        ],
        references=[
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS",
            "https://owasp.org/www-community/attacks/CORS_OriginHeaderScrutiny",
        ],
    ),
    RemediationGuide(
        check_id="cors_reflects_origin",
        title="CORS refleja origen arbitrario",
        explanation=(
            "Si el servidor refleja cualquier Origin en ACAO, un atacante puede "
            "leer datos del usuario autenticado desde su propio sitio."
        ),
        snippets=[
            CodeSnippet(
                platform="express",
                language="javascript",
                description="Validar orígenes en Express",
                code="""\
const allowedOrigins = ['https://app.example.com'];
app.use(cors({
  origin: (origin, cb) => {
    if (!origin || allowedOrigins.includes(origin)) cb(null, true);
    else cb(new Error('CORS no permitido'));
  },
}));""",
            ),
            CodeSnippet(
                platform="nginx",
                language="nginx",
                description="Whitelist de orígenes en nginx",
                code="""\
map $http_origin $cors_allowed {
    default 0;
    "https://app.example.com" 1;
    "https://admin.example.com" 1;
}""",
            ),
        ],
        references=[
            "https://portswigger.net/web-security/cors",
        ],
    ),
    # ── Formularios y CSRF ───────────────────────────────────
    RemediationGuide(
        check_id="form_missing_csrf",
        title="Formulario sin protección CSRF",
        explanation=(
            "Sin token CSRF, un atacante puede ejecutar acciones en nombre "
            "del usuario desde otro sitio web."
        ),
        snippets=[
            CodeSnippet(
                platform="django",
                language="python",
                description="CSRF en Django (activado por defecto)",
                code="""\
# En el template HTML:
# <form method="POST">{% csrf_token %}...</form>
#
# En settings.py asegurar que el middleware está activo:
MIDDLEWARE = [
    'django.middleware.csrf.CsrfViewMiddleware',
    # ...
]""",
            ),
            CodeSnippet(
                platform="express",
                language="javascript",
                description="CSRF con csurf en Express",
                code="""\
const csrf = require('csurf');
const csrfProtection = csrf({ cookie: true });

app.use(csrfProtection);
// En el template: <input type="hidden" name="_csrf" value="<%= csrfToken %>">""",
            ),
        ],
        references=[
            "https://owasp.org/www-community/attacks/csrf",
            "https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html",
        ],
    ),
    RemediationGuide(
        check_id="form_autocomplete_password",
        title="Autocomplete en campos de password",
        explanation=(
            "Aunque debatido, desactivar autocomplete en passwords en apps sensibles "
            "puede prevenir almacenamiento no deseado de credenciales."
        ),
        snippets=[
            CodeSnippet(
                platform="general",
                language="html",
                description="Desactivar autocomplete en input de password",
                code='<input type="password" name="password" autocomplete="new-password">',
            ),
        ],
        references=[
            "https://developer.mozilla.org/en-US/docs/Web/HTML/Attributes/autocomplete",
        ],
    ),
    # ── XSS ──────────────────────────────────────────────────
    RemediationGuide(
        check_id="xss_reflected",
        title="Reflexión XSS",
        explanation=(
            "Cuando la entrada del usuario se refleja sin encoding en el HTML, "
            "un atacante puede inyectar scripts maliciosos."
        ),
        snippets=[
            CodeSnippet(
                platform="express",
                language="javascript",
                description="Sanitizar input con express-validator y DOMPurify",
                code="""\
const { body, validationResult } = require('express-validator');
const createDOMPurify = require('dompurify');
const { JSDOM } = require('jsdom');
const DOMPurify = createDOMPurify(new JSDOM('').window);

// Validar y sanitizar input
app.post('/search', [
  body('q').trim().escape(),
], (req, res) => {
  const errors = validationResult(req);
  if (!errors.isEmpty()) return res.status(400).json({ errors: errors.array() });
  const safeQuery = DOMPurify.sanitize(req.body.q);
  // ...
});""",
            ),
            CodeSnippet(
                platform="general",
                language="html",
                description="DOMPurify en el cliente",
                code="""\
<script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"></script>
<script>
  const clean = DOMPurify.sanitize(userInput);
  document.getElementById('output').textContent = clean; // textContent, no innerHTML
</script>""",
            ),
        ],
        references=[
            "https://owasp.org/www-community/attacks/xss/",
            "https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html",
        ],
    ),
    # ── Open Redirect ────────────────────────────────────────
    RemediationGuide(
        check_id="open_redirect",
        title="Open Redirect",
        explanation=(
            "Un open redirect permite a atacantes redirigir a usuarios a sitios "
            "maliciosos usando tu dominio como intermediario."
        ),
        snippets=[
            CodeSnippet(
                platform="express",
                language="javascript",
                description="Validar redirect URLs en Express",
                code="""\
const url = require('url');
app.get('/redirect', (req, res) => {
  const target = req.query.url || '/';
  const parsed = url.parse(target);
  // Solo permitir redirects al mismo dominio
  if (parsed.host && parsed.host !== req.hostname) {
    return res.redirect('/');
  }
  res.redirect(target);
});""",
            ),
            CodeSnippet(
                platform="django",
                language="python",
                description="Validar redirect en Django",
                code="""\
from django.utils.http import url_has_allowed_host_and_scheme

def safe_redirect(request):
    next_url = request.GET.get('next', '/')
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = '/'
    return redirect(next_url)""",
            ),
        ],
        references=[
            "https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/11-Client-side_Testing/04-Testing_for_Client-side_URL_Redirect",
        ],
    ),
    # ── Rutas expuestas ──────────────────────────────────────
    RemediationGuide(
        check_id="path_env_exposed",
        title="Archivo .env expuesto",
        explanation=(
            "El archivo .env contiene credenciales, API keys y configuración sensible. "
            "Exponerlo públicamente es una vulnerabilidad crítica."
        ),
        snippets=[
            CodeSnippet(
                platform="nginx",
                language="nginx",
                description="Bloquear .env en nginx",
                code="""\
location ~ /\\.env {
    deny all;
    return 404;
}""",
            ),
            CodeSnippet(
                platform="apache",
                language="apache",
                description="Bloquear .env en Apache .htaccess",
                code="""\
<FilesMatch "^\\.env">
    Require all denied
</FilesMatch>""",
            ),
        ],
        references=[
            "https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/02-Configuration_and_Deployment_Management_Testing/05-Enumerate_Infrastructure_and_Application_Admin_Interfaces",
        ],
    ),
    RemediationGuide(
        check_id="path_git_exposed",
        title="Repositorio .git expuesto",
        explanation=(
            "Un directorio .git accesible permite descargar todo el código fuente, "
            "historial, credenciales y configuración del repositorio."
        ),
        snippets=[
            CodeSnippet(
                platform="nginx",
                language="nginx",
                description="Bloquear .git en nginx",
                code="""\
location ~ /\\.git {
    deny all;
    return 404;
}""",
            ),
            CodeSnippet(
                platform="apache",
                language="apache",
                description="Bloquear .git en Apache",
                code="""\
<DirectoryMatch "^\\.git">
    Require all denied
</DirectoryMatch>""",
            ),
            CodeSnippet(
                platform="general",
                language="bash",
                description="Agregar a .gitignore (no sube a producción)",
                code="# Asegurar que .git no se copie al deployment\n# En Dockerfile:\n# COPY --chown=node:node . . (sin .git)\n# .dockerignore:\n.git",
            ),
        ],
        references=[
            "https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/02-Configuration_and_Deployment_Management_Testing/05-Enumerate_Infrastructure_and_Application_Admin_Interfaces",
        ],
    ),
    # ── Email security ───────────────────────────────────────
    RemediationGuide(
        check_id="missing_spf",
        title="Sin registro SPF",
        explanation=(
            "SPF (Sender Policy Framework) especifica qué servidores pueden enviar "
            "email en nombre de tu dominio, previniendo spoofing."
        ),
        snippets=[
            CodeSnippet(
                platform="general",
                language="bash",
                description="Agregar registro SPF en DNS TXT",
                code="""\
# Registro TXT para el dominio raíz:
# Si usas Google Workspace:
v=spf1 include:_spf.google.com ~all

# Si usas Microsoft 365:
v=spf1 include:spf.protection.outlook.com ~all

# Si usas tu propio servidor:
v=spf1 ip4:YOUR_SERVER_IP ~all""",
            ),
        ],
        references=[
            "https://www.cloudflare.com/learning/dns/dns-records/dns-spf-record/",
            "https://dmarcian.com/spf-syntax-table/",
        ],
    ),
    RemediationGuide(
        check_id="missing_dmarc",
        title="Sin registro DMARC",
        explanation=(
            "DMARC dice a los servidores receptores qué hacer con emails que fallan "
            "SPF/DKIM, y envía reportes de intentos de spoofing."
        ),
        snippets=[
            CodeSnippet(
                platform="general",
                language="bash",
                description="Agregar registro DMARC en DNS TXT (_dmarc.dominio.com)",
                code="""\
# Registro TXT para _dmarc.tudominio.com:
# Empezar con monitoreo (p=none):
v=DMARC1; p=none; rua=mailto:dmarc-reports@tudominio.com; ruf=mailto:dmarc-reports@tudominio.com; fo=1

# Después de verificar, subir a quarantine:
v=DMARC1; p=quarantine; rua=mailto:dmarc-reports@tudominio.com

# Finalmente, reject:
v=DMARC1; p=reject; rua=mailto:dmarc-reports@tudominio.com""",
            ),
        ],
        references=[
            "https://dmarc.org/overview/",
            "https://www.cloudflare.com/learning/dns/dns-records/dns-dmarc-record/",
        ],
    ),
    RemediationGuide(
        check_id="missing_dkim",
        title="Sin registro DKIM",
        explanation=(
            "DKIM firma digitalmente los emails, permitiendo verificar que no fueron "
            "alterados en tránsito y que provienen de tu dominio."
        ),
        snippets=[
            CodeSnippet(
                platform="general",
                language="bash",
                description="Configurar DKIM depende del proveedor de email",
                code="""\
# Google Workspace: Admin Console > Apps > Google Workspace > Gmail > Authenticate email
# Microsoft 365: Microsoft 365 Defender > Email & collaboration > Policies > DKIM
# Postfix: usar opendkim
#   apt install opendkim opendkim-tools
#   opendkim-genkey -s default -d tudominio.com
#   # Publicar default._domainkey.tudominio.com como TXT record""",
            ),
        ],
        references=[
            "https://www.cloudflare.com/learning/dns/dns-records/dns-dkim-record/",
        ],
    ),
    # ── Métodos HTTP inseguros ───────────────────────────────
    RemediationGuide(
        check_id="unsafe_http_method",
        title="Métodos HTTP inseguros habilitados",
        explanation=(
            "Métodos como PUT, DELETE y TRACE pueden permitir modificación de recursos "
            "o facilitar ataques de cross-site tracing."
        ),
        snippets=[
            CodeSnippet(
                platform="nginx",
                language="nginx",
                description="Limitar métodos HTTP en nginx",
                code="""\
if ($request_method !~ ^(GET|HEAD|POST)$) {
    return 405;
}""",
            ),
            CodeSnippet(
                platform="apache",
                language="apache",
                description="Limitar métodos HTTP en Apache",
                code="""\
<LimitExcept GET POST HEAD>
    Require all denied
</LimitExcept>

# Deshabilitar TRACE globalmente:
TraceEnable Off""",
            ),
        ],
        references=[
            "https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/02-Configuration_and_Deployment_Management_Testing/06-Test_HTTP_Methods",
        ],
    ),
    # ── HTTPS Redirect ───────────────────────────────────────
    RemediationGuide(
        check_id="no_https_redirect",
        title="Sin redirección HTTP a HTTPS",
        explanation=(
            "Sin redirect automático, los usuarios que acceden por HTTP envían "
            "datos sin cifrar, vulnerables a interceptación."
        ),
        snippets=[
            CodeSnippet(
                platform="nginx",
                language="nginx",
                description="Redirect HTTP → HTTPS en nginx",
                code="""\
server {
    listen 80;
    server_name example.com;
    return 301 https://$host$request_uri;
}""",
            ),
            CodeSnippet(
                platform="apache",
                language="apache",
                description="Redirect HTTP → HTTPS en Apache .htaccess",
                code="""\
RewriteEngine On
RewriteCond %{HTTPS} off
RewriteRule ^(.*)$ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]""",
            ),
        ],
        references=[
            "https://letsencrypt.org/docs/",
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Redirections",
        ],
    ),
    # ── SRI ──────────────────────────────────────────────────
    RemediationGuide(
        check_id="missing_sri",
        title="Sin Subresource Integrity (SRI)",
        explanation=(
            "SRI verifica que los archivos cargados desde CDNs no fueron alterados. "
            "Sin SRI, un CDN comprometido puede inyectar código malicioso."
        ),
        snippets=[
            CodeSnippet(
                platform="general",
                language="html",
                description="Agregar integrity a scripts y stylesheets externos",
                code="""\
<!-- Generar hash: openssl dgst -sha384 -binary archivo.js | openssl base64 -A -->
<script src="https://cdn.example.com/lib.js"
        integrity="sha384-oqVuAfXRKap7fdgcCY5uykM6+R9GqQ8K/uxy9rx7HNQlGYl1kPzQho1wx4JwY8w"
        crossorigin="anonymous"></script>

<link rel="stylesheet" href="https://cdn.example.com/style.css"
      integrity="sha384-..."
      crossorigin="anonymous">""",
            ),
        ],
        references=[
            "https://developer.mozilla.org/en-US/docs/Web/Security/Subresource_Integrity",
            "https://www.srihash.org/",
        ],
    ),
    # ── Mixed Content ────────────────────────────────────────
    RemediationGuide(
        check_id="mixed_content",
        title="Contenido mixto (HTTP en HTTPS)",
        explanation=(
            "Cargar recursos HTTP en páginas HTTPS degrada la seguridad y causa "
            "warnings en los navegadores. Scripts HTTP pueden ser interceptados."
        ),
        snippets=[
            CodeSnippet(
                platform="general",
                language="html",
                description="CSP upgrade-insecure-requests como solución inmediata",
                code='<meta http-equiv="Content-Security-Policy" content="upgrade-insecure-requests">',
            ),
            CodeSnippet(
                platform="nginx",
                language="nginx",
                description="upgrade-insecure-requests via header en nginx",
                code='add_header Content-Security-Policy "upgrade-insecure-requests" always;',
            ),
        ],
        references=[
            "https://developer.mozilla.org/en-US/docs/Web/Security/Mixed_content",
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Security-Policy/upgrade-insecure-requests",
        ],
    ),
    # ── Directory Listing ────────────────────────────────────
    RemediationGuide(
        check_id="directory_listing",
        title="Directory listing habilitado",
        explanation=(
            "El listado de directorios expone la estructura de archivos del sitio, "
            "revelando archivos sensibles, backups y configuraciones."
        ),
        snippets=[
            CodeSnippet(
                platform="nginx",
                language="nginx",
                description="Deshabilitar autoindex en nginx",
                code="autoindex off;  # En el server o location block",
            ),
            CodeSnippet(
                platform="apache",
                language="apache",
                description="Deshabilitar directory listing en Apache",
                code="Options -Indexes",
            ),
        ],
        references=[
            "https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/02-Configuration_and_Deployment_Management_Testing/04-Review_Old_Backup_and_Unreferenced_Files_for_Sensitive_Information",
        ],
    ),
    # ── HTML Leaks ───────────────────────────────────────────
    RemediationGuide(
        check_id="html_version_leak",
        title="Versiones expuestas en HTML",
        explanation=(
            "Meta tags con versiones de CMS o frameworks facilitan "
            "ataques dirigidos a vulnerabilidades conocidas de esa versión."
        ),
        snippets=[
            CodeSnippet(
                platform="general",
                language="html",
                description="Eliminar meta generator en WordPress",
                code="""\
<!-- En functions.php de WordPress: -->
<?php remove_action('wp_head', 'wp_generator'); ?>

<!-- O en HTML, eliminar: -->
<!-- <meta name="generator" content="WordPress 6.4.2"> -->""",
            ),
        ],
        references=[
            "https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/01-Information_Gathering/02-Fingerprint_Web_Server",
        ],
    ),
    RemediationGuide(
        check_id="html_comment_leak",
        title="Comentarios HTML con información sensible",
        explanation=(
            "Comentarios de depuración en producción pueden revelar rutas internas, "
            "credenciales, TODO items y lógica de negocio."
        ),
        snippets=[
            CodeSnippet(
                platform="general",
                language="bash",
                description="Eliminar comentarios en build de producción",
                code="""\
# Webpack (terser plugin):
# optimization: { minimizer: [new TerserPlugin({ extractComments: false })] }

# Vite/Rollup:
# build: { rollupOptions: { output: { manualChunks: ... } } }

# O usar html-minifier-terser:
npx html-minifier-terser --remove-comments --input index.html --output dist/index.html""",
            ),
        ],
        references=[
            "https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/01-Information_Gathering/05-Review_Webpage_Content_for_Information_Leakage",
        ],
    ),
    # ── CSP unsafe ───────────────────────────────────────────
    RemediationGuide(
        check_id="csp_unsafe_inline",
        title="CSP con 'unsafe-inline'",
        explanation=(
            "'unsafe-inline' permite ejecutar scripts inline, que es exactamente "
            "lo que CSP debería prevenir. Esto anula gran parte de la protección."
        ),
        snippets=[
            CodeSnippet(
                platform="general",
                language="html",
                description="Usar nonce-based CSP en lugar de unsafe-inline",
                code="""\
<!-- En el servidor, generar un nonce aleatorio por request: -->
<!-- Header: Content-Security-Policy: script-src 'nonce-abc123' -->

<script nonce="abc123">
  // Este script se ejecuta porque tiene el nonce correcto
  console.log('Safe inline script');
</script>""",
            ),
            CodeSnippet(
                platform="express",
                language="javascript",
                description="Nonce-based CSP con helmet en Express",
                code="""\
const crypto = require('crypto');

app.use((req, res, next) => {
  res.locals.nonce = crypto.randomBytes(16).toString('base64');
  next();
});

app.use(helmet.contentSecurityPolicy({
  directives: {
    scriptSrc: ["'self'", (req, res) => `'nonce-${res.locals.nonce}'`],
    styleSrc: ["'self'", (req, res) => `'nonce-${res.locals.nonce}'`],
  },
}));""",
            ),
        ],
        references=[
            "https://web.dev/articles/strict-csp",
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Security-Policy/script-src",
        ],
    ),
    RemediationGuide(
        check_id="csp_unsafe_eval",
        title="CSP con 'unsafe-eval'",
        explanation=(
            "'unsafe-eval' permite eval(), Function(), setTimeout(string), etc. "
            "Estas funciones son vectores comunes de inyección de código."
        ),
        snippets=[
            CodeSnippet(
                platform="general",
                language="javascript",
                description="Refactorizar código que usa eval()",
                code="""\
// EN LUGAR DE:
// eval('var x = ' + jsonString);
// setTimeout('doSomething()', 1000);
// new Function('return ' + expr)();

// USAR:
const x = JSON.parse(jsonString);
setTimeout(doSomething, 1000);
// Para expresiones dinámicas, considerar un parser seguro""",
            ),
        ],
        references=[
            "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/eval#never_use_eval!",
        ],
    ),
]

# Indexar por check_id para búsquedas O(1)
_REMEDIATION_INDEX = {guide.check_id: guide for guide in REMEDIATION_DB}


# ── Funciones públicas ───────────────────────────────────────


def get_remediation(check_id: str) -> Optional[RemediationGuide]:
    """Obtiene la guía de remediación para un check_id."""
    return _REMEDIATION_INDEX.get(check_id)


def get_remediations_for_findings(findings: List[Finding]) -> List[RemediationGuide]:
    """Filtra y retorna remediaciones relevantes para una lista de findings."""
    seen = set()
    guides: List[RemediationGuide] = []
    for finding in findings:
        cid = finding.check_id
        # Normalizar: header-missing-content-security-policy → missing_csp
        normalized = _normalize_check_id(cid)
        if normalized and normalized not in seen:
            guide = _REMEDIATION_INDEX.get(normalized)
            if guide:
                seen.add(normalized)
                guides.append(guide)
    return guides


def format_remediation_markdown(guide: RemediationGuide) -> str:
    """Genera Markdown con bloques colapsables <details> por plataforma."""
    lines: List[str] = []
    lines.append(f"### {guide.check_id} — {guide.title}")
    lines.append("")
    lines.append(f"**Por qué:** {guide.explanation}")
    lines.append("")

    for snippet in guide.snippets:
        lines.append(f"<details>")
        lines.append(f"<summary>{snippet.platform.title()} — {snippet.description}</summary>")
        lines.append("")
        lines.append(f"```{snippet.language}")
        lines.append(snippet.code)
        lines.append("```")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    if guide.references:
        lines.append("**Referencias:**")
        for ref in guide.references:
            lines.append(f"- {ref}")
        lines.append("")

    return "\n".join(lines)


# ── Mapeo de check_id del scanner → check_id de remediación ─


_CHECK_ID_MAP = {
    # Headers
    "header-missing-content-security-policy": "missing_csp",
    "header-missing-strict-transport-security": "missing_hsts",
    "header-missing-x-frame-options": "missing_x_frame_options",
    "header-missing-x-content-type-options": "missing_x_content_type",
    "header-missing-referrer-policy": "missing_referrer_policy",
    "header-missing-permissions-policy": "missing_permissions_policy",
    "header-disclosure-server": "server_info_disclosure",
    "header-disclosure-x-powered-by": "server_info_disclosure",
    # Cookies
    "cookie-no-secure": "cookie_no_secure",
    "cookie-no-httponly": "cookie_no_httponly",
    "cookie-no-samesite": "cookie_no_samesite",
    # SSL
    "ssl-expiring-soon": "ssl_expires_soon",
    "ssl-weak-protocol": "ssl_weak_protocol",
    # CORS
    "cors-wildcard-credentials": "cors_wildcard",
    "cors-origin-reflected": "cors_reflects_origin",
    # Forms
    "form-no-csrf": "form_missing_csrf",
    # XSS
    "xss-reflection-detected": "xss_reflected",
    # Redirects
    "open-redirect-detected": "open_redirect",
    # Paths
    "path-sensitive-.env": "path_env_exposed",
    "path-sensitive-.git-head": "path_git_exposed",
    "path-sensitive-.git-config": "path_git_exposed",
    # Nuevos
    "unsafe-http-methods": "unsafe_http_method",
    "no-https-redirect": "no_https_redirect",
    "missing-sri": "missing_sri",
    "mixed-content": "mixed_content",
    "directory-listing": "directory_listing",
    "html-version-leak": "html_version_leak",
    "html-comment-leak": "html_comment_leak",
    "missing-csp": "missing_csp",
    "csp-unsafe-inline": "csp_unsafe_inline",
    "csp-unsafe-eval": "csp_unsafe_eval",
    "missing-spf": "missing_spf",
    "missing-dmarc": "missing_dmarc",
    "missing-dkim": "missing_dkim",
    "dns-no-spf": "missing_spf",
    "dns-no-dmarc": "missing_dmarc",
}


def _normalize_check_id(raw_check_id: str) -> Optional[str]:
    """Normaliza un check_id del scanner al ID de remediación."""
    # Intentar mapeo directo
    mapped = _CHECK_ID_MAP.get(raw_check_id)
    if mapped:
        return mapped
    # Intentar prefijos para cookies con nombre dinámico
    for prefix, target in [
        ("cookie-no-secure-", "cookie_no_secure"),
        ("cookie-no-httponly-", "cookie_no_httponly"),
        ("cookie-no-samesite-", "cookie_no_samesite"),
    ]:
        if raw_check_id.startswith(prefix):
            return target
    return None
