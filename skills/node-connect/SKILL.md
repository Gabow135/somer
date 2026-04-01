---
name: node-connect
description: Diagnose SOMER node connection and pairing failures for Android, iOS, and macOS companion apps. Use when QR/setup code/manual connect fails, local Wi-Fi works but VPS/tailnet does not, or errors mention pairing required, unauthorized, bootstrap token invalid or expired, gateway.bind, gateway.remote.url, Tailscale, or plugins.entries.device-pair.config.publicUrl.
---

# Node Connect

Goal: find the one real route from node -> gateway, verify SOMER is advertising that route, then fix pairing/auth.

## Topology first

Decide which case you are in before proposing fixes:

- same machine / emulator / USB tunnel
- same LAN / local Wi-Fi
- same Tailscale tailnet
- public URL / reverse proxy

Do not mix them.

- Local Wi-Fi problem: do not switch to Tailscale unless remote access is actually needed.
- VPS / remote gateway problem: do not keep debugging `localhost` or LAN IPs.

## If ambiguous, ask first

If the setup is unclear or the failure report is vague, ask short clarifying questions before diagnosing.

Ask for:

- which route they intend: same machine, same LAN, Tailscale tailnet, or public URL
- whether they used QR/setup code or manual host/port
- the exact app text/status/error, quoted exactly if possible
- whether `somer devices list` shows a pending pairing request

Do not guess from `can't connect`.

## Canonical checks

Prefer `somer qr --json`. It uses the same setup-code payload Android scans.

```bash
somer config get gateway.mode
somer config get gateway.bind
somer config get gateway.tailscale.mode
somer config get gateway.remote.url
somer config get gateway.auth.mode
somer config get gateway.auth.allowTailscale
somer config get plugins.entries.device-pair.config.publicUrl
somer qr --json
somer devices list
somer nodes status
```

If this SOMER instance is pointed at a remote gateway, also run:

```bash
somer qr --remote --json
```

If Tailscale is part of the story:

```bash
tailscale status --json
```

## Read the result, not guesses

`somer qr --json` success means:

- `gatewayUrl`: this is the actual endpoint the app should use.
- `urlSource`: this tells you which config path won.

Common good sources:

- `gateway.bind=lan`: same Wi-Fi / LAN only
- `gateway.bind=tailnet`: direct tailnet access
- `gateway.tailscale.mode=serve` or `gateway.tailscale.mode=funnel`: Tailscale route
- `plugins.entries.device-pair.config.publicUrl`: explicit public/reverse-proxy route
- `gateway.remote.url`: remote gateway route

## Root-cause map

If `somer qr --json` says `Gateway is only bound to loopback`:

- remote node cannot connect yet
- fix the route, then generate a fresh setup code
- `gateway.bind=auto` is not enough if the effective QR route is still loopback
- same LAN: use `gateway.bind=lan`
- same tailnet: prefer `gateway.tailscale.mode=serve` or use `gateway.bind=tailnet`
- public internet: set a real `plugins.entries.device-pair.config.publicUrl` or `gateway.remote.url`

If `gateway.bind=tailnet set, but no tailnet IP was found`:

- gateway host is not actually on Tailscale

If `qr --remote requires gateway.remote.url`:

- remote-mode config is incomplete

If the app says `pairing required`:

- network route and auth worked
- approve the pending device

```bash
somer devices list
somer devices approve --latest
```

If the app says `bootstrap token invalid or expired`:

- old setup code
- generate a fresh one and rescan
- do this after any URL/auth fix too

If the app says `unauthorized`:

- wrong token/password, or wrong Tailscale expectation
- for Tailscale Serve, `gateway.auth.allowTailscale` must match the intended flow
- otherwise use explicit token/password

## Fast heuristics

- Same Wi-Fi setup + gateway advertises `127.0.0.1`, `localhost`, or loopback-only config: wrong.
- Remote setup + setup/manual uses private LAN IP: wrong.
- Tailnet setup + gateway advertises LAN IP instead of MagicDNS / tailnet route: wrong.
- Public URL set but QR still advertises something else: inspect `urlSource`; config is not what you think.
- `somer devices list` shows pending requests: stop changing network config and approve first.

## Fix style

Reply with one concrete diagnosis and one route.

If there is not enough signal yet, ask for setup + exact app text instead of guessing.

Good:

- `The gateway is still loopback-only, so a node on another network can never reach it. Enable Tailscale Serve, restart the gateway, run somer qr again, rescan, then approve the pending device pairing.`

Bad:

- `Maybe LAN, maybe Tailscale, maybe port forwarding, maybe public URL.`

## Formato de Respuesta

**Usar plantilla `TPL-STATUS`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
ESTADO — Node Connect | 26/Mar/2026

ESTADO GENERAL: WARN

CHECKS
  [OK] Gateway: ws://127.0.0.1:18789 activo
  [OK] Red: Puerto 18789 accesible
  [!]  Nodo: iPhone de Gabriel — no responde desde 09:00
  [OK] Auth: Token de pairing válido

ALERTAS
  [!] Nodo "iPhone de Gabriel" desconectado — verificar WiFi o reiniciar app

---
Verificado por: SOMER | Servicio: Node Connect
```
