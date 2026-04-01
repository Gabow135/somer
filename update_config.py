import json
import os

# Ruta del archivo de configuración
config_path = os.path.expanduser('~/.somer/config.json')

# Leer configuración actual
with open(config_path, 'r') as f:
    config = json.load(f)

# Modificar configuración del gateway para que sea accesible públicamente
config['gateway']['bind'] = 'auto'  # Cambiar de 'loopback' a 'auto'
config['gateway']['host'] = '0.0.0.0'  # Escuchar en todas las interfaces

# Agregar configuración de webhook para Telegram
if 'channels' not in config:
    config['channels'] = {}
if 'entries' not in config['channels']:
    config['channels']['entries'] = {}
if 'telegram' not in config['channels']['entries']:
    config['channels']['entries']['telegram'] = {}

telegram_config = config['channels']['entries']['telegram']
if 'config' not in telegram_config:
    telegram_config['config'] = {}

# Agregar configuración de webhook
telegram_config['config']['webhook_enabled'] = True
telegram_config['config']['webhook_path'] = '/webhook/telegram'

# Guardar configuración actualizada
with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)

print('✅ Configuración actualizada:')
print('   - Gateway bind: auto')
print('   - Gateway host: 0.0.0.0')
print('   - Webhook habilitado para Telegram')
print('   - Backup guardado en ~/.somer/config.json.backup')
