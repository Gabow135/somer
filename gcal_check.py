import urllib.request
import urllib.parse
import json
import os
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/.somer/.env"))

token_file = os.path.expanduser('~/.somer/google_calendar_token.json')
client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")

with open(token_file) as f:
    tokens = json.load(f)

refresh_token = tokens['refresh_token']
data = urllib.parse.urlencode({
    'client_id': client_id,
    'client_secret': client_secret,
    'refresh_token': refresh_token,
    'grant_type': 'refresh_token'
}).encode()
req = urllib.request.Request(
    'https://oauth2.googleapis.com/token',
    data=data,
    headers={'Content-Type': 'application/x-www-form-urlencoded'},
    method='POST'
)
with urllib.request.urlopen(req, timeout=15) as resp:
    new_tokens = json.loads(resp.read().decode())

access_token = new_tokens['access_token']
new_tokens['refresh_token'] = refresh_token
with open(token_file, 'w') as f:
    json.dump(new_tokens, f, indent=2)

req2 = urllib.request.Request(
    'https://www.googleapis.com/calendar/v3/users/me/calendarList',
    headers={'Authorization': f'Bearer {access_token}'}
)
with urllib.request.urlopen(req2, timeout=15) as resp:
    cals = json.loads(resp.read().decode())

print('CALENDARIOS:')
for c in cals.get('items', []):
    print(f"  {c['summary']} -- {c['id']}")

from datetime import datetime, timezone, timedelta
tz = timezone(timedelta(hours=-5))
today = datetime.now(tz)
time_min = today.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
time_max = today.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
gcal_url = (
    'https://www.googleapis.com/calendar/v3/calendars/primary/events'
    '?timeMin=' + urllib.parse.quote(time_min)
    + '&timeMax=' + urllib.parse.quote(time_max)
    + '&singleEvents=true&orderBy=startTime'
)
req3 = urllib.request.Request(gcal_url, headers={'Authorization': f'Bearer {access_token}'})
with urllib.request.urlopen(req3, timeout=15) as resp:
    events = json.loads(resp.read().decode())

print('EVENTOS HOY:')
items = events.get('items', [])
if not items:
    print('  (sin eventos)')
for e in items:
    raw = e.get('start', {}).get('dateTime', e.get('start', {}).get('date', '?'))
    try:
        from datetime import datetime as _dt
        t = _dt.fromisoformat(raw).strftime('%H:%M')
    except Exception:
        t = raw
    print(f"  {t} -- {e.get('summary', '(sin titulo)')}")
