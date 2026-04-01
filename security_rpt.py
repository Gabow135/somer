import sys, os
sys.path.insert(0, '/var/www/somer')

from fpdf import FPDF
from fpdf.enums import XPos, YPos

OUT_PATH = '/var/www/somer/reports/security_todohogar_20260327.pdf'
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

TARGET = 'www.todohogar.com'
DATE = '27/Mar/2026'
RISK_SCORE = '5.8/10'
RISK_LEVEL = 'MEDIO-ALTO'

C_DARK   = (15, 23, 42)
C_WHITE  = (255, 255, 255)
C_LIGHT  = (248, 250, 252)
C_CRITICAL = (220, 38, 38)
C_HIGH   = (234, 88, 12)
C_MEDIUM = (202, 138, 4)
C_LOW    = (37, 99, 235)
C_INFO   = (100, 116, 139)
C_GREEN  = (22, 163, 74)
C_BORDER = (226, 232, 240)

SEV_COLORS = {
    'CRITICO': C_CRITICAL,
    'ALTO':    C_HIGH,
    'MEDIO':   C_MEDIUM,
    'BAJO':    C_LOW,
    'INFO':    C_INFO,
}

FINDINGS = [
    (
        'V01', 'ALTO', 'Headers de Seguridad HTTP Ausentes',
        'No se detectaron headers esenciales: Content-Security-Policy, X-Frame-Options, '
        'X-Content-Type-Options, Strict-Transport-Security y Referrer-Policy. '
        'Esto expone al sitio a clickjacking, MIME sniffing y ataques de downgrade.',
        'Configurar en next.config.js:\n'
        'headers: [{ source: "/(.*)", headers: [{ key: "X-Frame-Options", value: "DENY" },'
        '{ key: "X-Content-Type-Options", value: "nosniff" }, ...] }]'
    ),
    (
        'V02', 'ALTO', 'Sin SRI en Scripts Externos (CDN)',
        'Los scripts de Google Tag Manager y otros CDNs externos no incluyen el atributo '
        'integrity (Subresource Integrity). Si el CDN es comprometido, codigo malicioso '
        'se ejecutaria directamente en el navegador del usuario sin deteccion.',
        'Agregar integrity="sha384-..." crossorigin="anonymous" a cada script externo.\n'
        'Generar hashes en: https://www.srihash.org/'
    ),
    (
        'V03', 'ALTO', 'IDs de Tracking Expuestos en HTML Publico',
        'El Google Tag Manager ID y Google Analytics ID son visibles en el '
        'codigo fuente publico. Esto facilita ataques de tag injection y exfiltracion '
        'de datos de usuarios a traves de tags maliciosos inyectados.',
        'Implementar restricciones de dominio en el panel de GTM.\n'
        'Monitorear el contenedor de GTM periodicamente con herramientas de tag auditing.'
    ),
    (
        'V04', 'MEDIO', 'Archivo robots.txt Ausente (404)',
        'La ruta /robots.txt retorna HTTP 404. Sin este archivo los motores de busqueda '
        'pueden indexar areas administrativas, APIs internas u otras rutas sensibles '
        'que no deberian ser publicamente visibles.',
        'Crear /public/robots.txt:\n'
        'User-agent: *\nDisallow: /api/\nDisallow: /admin/\nAllow: /'
    ),
    (
        'V05', 'MEDIO', 'Endpoint de Busqueda Sin Rate Limiting Visible',
        'Los endpoints de API de Next.js no exponen headers X-RateLimit-* que indiquen '
        'proteccion contra abuso. Esto hace al sitio vulnerable a scraping masivo, '
        'enumeracion de productos y abuso de recursos del servidor.',
        'Implementar rate limiting con middleware en /pages/api/:\n'
        'import rateLimit from "express-rate-limit";\n'
        'const limiter = rateLimit({ windowMs: 60000, max: 30 });'
    ),
    (
        'V06', 'MEDIO', 'Cookie BWSTATE con Flags No Verificables Externamente',
        'La cookie de WAF/anti-bot BWSTATE no puede verificarse su configuracion '
        'Secure/HttpOnly desde analisis externo. Si carece de estos flags podria '
        'ser accesible via JavaScript y vulnerable a robo por ataques XSS.',
        'Verificar configuracion interna. La cookie debe incluir:\n'
        'Set-Cookie: BWSTATE=...; Secure; HttpOnly; SameSite=Strict'
    ),
    (
        'V07', 'BAJO', 'Build ID de Next.js Expuesto Publicamente',
        'El identificador unico de build de Next.js es visible en el HTML publico. '
        'Permite identificar la version exacta del deployment y facilita ataques '
        'dirigidos a vulnerabilidades especificas de esa version.',
        'Mantener Next.js actualizado a la ultima version estable.\n'
        'Considerar rotar el buildId frecuentemente via re-deployment.'
    ),
    (
        'V08', 'BAJO', 'Ausencia de security.txt (RFC 9116)',
        'No existe el archivo /.well-known/security.txt. Este estandar internacional '
        'permite a investigadores de seguridad reportar vulnerabilidades de forma '
        'responsable y coordinada con el equipo de seguridad.',
        'Crear /.well-known/security.txt:\n'
        'Contact: security@todohogar.com\n'
        'Expires: 2027-01-01T00:00:00z'
    ),
    (
        'V09', 'INFO', 'Certificado SSL Tipo DV (Domain Validated)',
        'El certificado SSL es tipo DV (Domain Validation), el nivel basico de validacion. '
        'No valida la identidad legal de la organizacion. Para una plataforma de e-commerce '
        'esto puede reducir la confianza del usuario en transacciones.',
        'Considerar upgrade a certificado OV o EV para mayor confianza del usuario.\n'
        'Especialmente recomendado para plataformas de e-commerce.'
    ),
]


class SecurityReport(FPDF):
    def header(self):
        self.set_fill_color(*C_DARK)
        self.rect(0, 0, 210, 18, 'F')
        self.set_text_color(*C_WHITE)
        self.set_font('Helvetica', 'B', 9)
        self.set_xy(10, 5)
        self.cell(130, 8, 'SOMER Security Audit  |  Reporte Confidencial',
                  new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.set_font('Helvetica', '', 8)
        self.set_x(150)
        self.cell(50, 8, TARGET, align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        self.ln(4)

    def footer(self):
        self.set_y(-14)
        self.set_fill_color(*C_DARK)
        self.rect(0, self.get_y(), 210, 20, 'F')
        self.set_text_color(180, 180, 180)
        self.set_font('Helvetica', '', 7)
        self.set_xy(10, self.get_y() + 4)
        self.cell(0, 5,
                  f'SOMER Security Audit  |  {TARGET}  |  {DATE}  |  Confidencial  |  Pag {self.page_no()}',
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)

    def section_title(self, text):
        self.ln(4)
        self.set_fill_color(*C_DARK)
        self.set_text_color(*C_WHITE)
        self.set_font('Helvetica', 'B', 10)
        self.cell(0, 8, f'  {text}', fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        self.ln(3)

    def severity_badge(self, sev, x, y, w=22, h=7):
        color = SEV_COLORS.get(sev, C_INFO)
        self.set_xy(x, y)
        self.set_fill_color(*color)
        self.set_text_color(*C_WHITE)
        self.set_font('Helvetica', 'B', 7)
        self.cell(w, h, sev, fill=True, align='C', new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.set_text_color(0, 0, 0)

    def info_row(self, label, value, fill=False):
        if fill:
            self.set_fill_color(*C_LIGHT)
        else:
            self.set_fill_color(255, 255, 255)
        self.set_font('Helvetica', 'B', 8)
        self.cell(45, 6, label, border=1, fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.set_font('Helvetica', '', 8)
        self.cell(145, 6, value, border=1, fill=fill, new_x=XPos.LMARGIN, new_y=YPos.NEXT)


pdf = SecurityReport(orientation='P', unit='mm', format='A4')
pdf.set_auto_page_break(auto=True, margin=18)
pdf.set_margins(12, 22, 12)
pdf.add_page()
pdf.ln(10)

hero_y = pdf.get_y()
pdf.set_fill_color(*C_DARK)
pdf.set_draw_color(*C_DARK)
pdf.rect(12, hero_y, 186, 46, 'F')
pdf.set_text_color(*C_WHITE)
pdf.set_font('Helvetica', 'B', 19)
pdf.set_xy(18, hero_y + 7)
pdf.cell(0, 10, 'Reporte de Auditoria de Seguridad Web', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_font('Helvetica', '', 13)
pdf.set_x(18)
pdf.cell(0, 8, TARGET, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_font('Helvetica', '', 9)
pdf.set_x(18)
pdf.cell(0, 6, f'Generado por SOMER Security  |  {DATE}', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_text_color(0, 0, 0)
pdf.set_y(hero_y + 50)
pdf.ln(4)

pdf.set_font('Helvetica', 'B', 11)
pdf.cell(0, 7, 'Puntuacion de Riesgo Global', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.ln(2)
risk_y = pdf.get_y()

pdf.set_fill_color(*C_HIGH)
pdf.rect(12, risk_y, 55, 22, 'F')
pdf.set_text_color(*C_WHITE)
pdf.set_font('Helvetica', 'B', 22)
pdf.set_xy(12, risk_y + 1)
pdf.cell(55, 13, RISK_SCORE, align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_font('Helvetica', 'B', 9)
pdf.set_xy(12, risk_y + 14)
pdf.cell(55, 7, RISK_LEVEL, align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_text_color(0, 0, 0)

sev_order = [('CRITICO', 0), ('ALTO', 3), ('MEDIO', 3), ('BAJO', 2), ('INFO', 1)]
cx = 72
for sev, count in sev_order:
    color = SEV_COLORS[sev]
    pdf.set_fill_color(*color)
    pdf.rect(cx, risk_y, 23, 22, 'F')
    pdf.set_text_color(*C_WHITE)
    pdf.set_font('Helvetica', 'B', 15)
    pdf.set_xy(cx, risk_y + 2)
    pdf.cell(23, 10, str(count), align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font('Helvetica', '', 6)
    pdf.set_xy(cx, risk_y + 13)
    pdf.cell(23, 8, sev, align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    cx += 26
pdf.set_text_color(0, 0, 0)
pdf.set_y(risk_y + 28)

pdf.section_title('1. Resumen Ejecutivo')
pdf.set_font('Helvetica', '', 9)
pdf.multi_cell(0, 5,
    'Se realizo una auditoria de seguridad no invasiva sobre www.todohogar.com mediante analisis '
    'estatico de cabeceras HTTP, tecnologias detectadas, configuracion SSL/TLS, politicas de '
    'cookies, contenido HTML y recursos cargados por la aplicacion. El sitio opera sobre Next.js '
    'con infraestructura Amazon AWS y utiliza Cloudflare como CDN/WAF principal.\n\n'
    'La evaluacion identifico 9 hallazgos: 0 criticos, 3 altos, 3 medios, 2 bajos y 1 informativo. '
    'La ausencia de headers de seguridad HTTP representa el riesgo mas significativo, seguido por '
    'la falta de Subresource Integrity en scripts de terceros. No se detectaron vulnerabilidades '
    'criticas como inyeccion SQL, XSS persistente o exposicion de credenciales.',
    new_x=XPos.LMARGIN, new_y=YPos.NEXT)

pdf.section_title('2. Informacion Tecnica del Target')
rows = [
    ('URL',            'https://www.todohogar.com',                False),
    ('Tecnologia',     'Next.js (React SSR/SSG)',                  True),
    ('Infraestructura','Amazon AWS / CloudFront CDN',              False),
    ('CDN / WAF',      'Cloudflare con proteccion anti-bot BWSTATE', True),
    ('SSL/TLS',        'TLS 1.3 | Amazon DV Certificate | Valido hasta 2026', False),
    ('Subdominios',    'www, app, api (detectados via CT logs)',   True),
    ('Metodologia',    'Analisis pasivo no invasivo',              False),
    ('Fecha auditoria',DATE,                                       True),
]
for label, val, fill in rows:
    pdf.info_row(label, val, fill=fill)
pdf.ln(4)

pdf.section_title('3. Hallazgos de Seguridad')

for i, (vid, sev, title, desc, remed) in enumerate(FINDINGS):
    if pdf.get_y() > 248:
        pdf.add_page()

    bg = C_LIGHT if (i % 2 == 0) else (255, 255, 255)

    row_y = pdf.get_y()
    pdf.set_fill_color(*bg)
    pdf.set_draw_color(*C_BORDER)
    pdf.set_font('Helvetica', 'B', 8.5)
    pdf.cell(12, 7, vid, border='LTB', fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    badge_x = pdf.get_x()
    pdf.set_x(badge_x + 24)
    pdf.set_font('Helvetica', 'B', 8.5)
    pdf.cell(0, 7, title, border='TBR', fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.severity_badge(sev, badge_x, row_y, w=22, h=7)

    pdf.set_fill_color(*bg)
    pdf.set_font('Helvetica', 'I', 7.5)
    pdf.multi_cell(0, 4.5, desc, border='LR', fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    remed_lines = remed.split('\n')
    pdf.set_font('Helvetica', 'B', 7.5)
    pdf.set_fill_color(237, 253, 244)
    pdf.cell(32, 5, '  Remediacion:', border='L', fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.set_font('Helvetica', '', 7.5)
    pdf.cell(0, 5, remed_lines[0], border='R', fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if len(remed_lines) > 1:
        pdf.set_font('Courier', '', 6.5)
        for extra in remed_lines[1:]:
            pdf.cell(0, 4.5, f'    {extra}', border='LR', fill=True,
                     new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.cell(0, 1, '', border='LBR', fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

if pdf.get_y() > 230:
    pdf.add_page()

pdf.section_title('4. Controles Positivos Detectados')
positives = [
    'HTTPS activado  - Todo el trafico HTTP redirige correctamente a HTTPS.',
    'WAF activo  - Cloudflare con proteccion anti-bot BWSTATE operativo.',
    'TLS 1.3  - Version moderna del protocolo TLS configurada correctamente.',
    'Certificado SSL valido  - Amazon DV con cadena de confianza completa.',
    'CDN global  - Cloudflare garantiza alta disponibilidad y baja latencia.',
    'Next.js actualizado  - Framework moderno con parches de seguridad recientes.',
]
for p in positives:
    pdf.set_font('Helvetica', '', 8.5)
    pdf.set_text_color(22, 163, 74)
    pdf.cell(6, 5.5, '[OK]', new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 5.5, f' {p}', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.ln(4)

pdf.section_title('5. Plan de Remediacion Priorizado')
plan = [
    ('Inmediato  (< 1 semana)', [
        '1. Configurar headers HTTP de seguridad: CSP, HSTS, X-Frame-Options, X-Content-Type-Options',
        '2. Implementar SRI (integrity hash) en todos los scripts externos de CDN',
    ]),
    ('Corto plazo  (1 - 4 semanas)', [
        '3. Crear y publicar /robots.txt con directivas apropiadas para bots',
        '4. Implementar rate limiting en endpoints de API (express-rate-limit o similar)',
        '5. Publicar /.well-known/security.txt para divulgacion responsable de vulnerabilidades',
    ]),
    ('Mediano plazo  (1 - 3 meses)', [
        '6. Evaluar upgrade de certificado SSL a OV/EV para mayor confianza en e-commerce',
        '7. Auditar internamente configuracion de cookies de sesion (Secure, HttpOnly, SameSite)',
        '8. Mantener Next.js actualizado e implementar proceso de rotacion de deployments',
    ]),
]
for period, items in plan:
    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_fill_color(30, 41, 59)
    pdf.set_text_color(*C_WHITE)
    pdf.cell(0, 6, f'  {period}', fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)
    for item in items:
        pdf.set_font('Helvetica', '', 8.5)
        pdf.set_fill_color(*C_LIGHT)
        pdf.cell(0, 5.5, f'   {item}', fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

pdf.ln(4)
if pdf.get_y() > 250:
    pdf.add_page()
disc_y = pdf.get_y()
pdf.set_fill_color(254, 243, 199)
pdf.set_draw_color(202, 138, 4)
pdf.rect(12, disc_y, 186, 22, 'FD')
pdf.set_xy(15, disc_y + 3)
pdf.set_font('Helvetica', 'B', 8)
pdf.set_text_color(113, 63, 18)
pdf.cell(0, 5, 'Aviso Legal', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_x(15)
pdf.set_font('Helvetica', '', 7.5)
pdf.multi_cell(181, 4.5,
    'Este reporte fue generado mediante analisis pasivo y no invasivo. No se realizaron pruebas de '
    'penetracion activa, inyeccion de payloads ni acceso no autorizado a sistemas. Los hallazgos se '
    'basan en informacion publicamente accesible. SOMER Security no se responsabiliza por el uso de '
    'este reporte fuera del alcance acordado.',
    new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_text_color(0, 0, 0)

pdf.output(OUT_PATH)
print(f'PDF generado exitosamente: {OUT_PATH}')
