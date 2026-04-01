"""Constantes globales de SOMER 2.0."""

from pathlib import Path

# ── Versión ──────────────────────────────────────────────────
VERSION = "2.0.0-alpha"
APP_NAME = "somer"

# ── Rutas por defecto ────────────────────────────────────────
DEFAULT_HOME = Path.home() / ".somer"
DEFAULT_CONFIG_PATH = DEFAULT_HOME / "config.json"
DEFAULT_CREDENTIALS_DIR = DEFAULT_HOME / "credentials"
DEFAULT_SESSIONS_DIR = DEFAULT_HOME / "sessions"
DEFAULT_MEMORY_DIR = DEFAULT_HOME / "memory"
DEFAULT_LOGS_DIR = DEFAULT_HOME / "logs"

# ── Gateway ──────────────────────────────────────────────────
GATEWAY_HOST = "127.0.0.1"
GATEWAY_PORT = 18789
GATEWAY_URL = f"ws://{GATEWAY_HOST}:{GATEWAY_PORT}"

# ── Tokens ───────────────────────────────────────────────────
DEFAULT_MAX_CONTEXT_TOKENS = 128_000
DEFAULT_MAX_OUTPUT_TOKENS = 8_192
COMPACT_THRESHOLD_RATIO = 0.85  # Compactar al 85% del límite

# ── Modelos por defecto ──────────────────────────────────────
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
DEFAULT_FAST_MODEL = "claude-haiku-4-5-20251001"

# ── Sesiones ─────────────────────────────────────────────────
SESSION_IDLE_TIMEOUT_SECS = 3600  # 1 hora
SESSION_MAX_TURNS = 200

# ── Memory ───────────────────────────────────────────────────
MEMORY_EMBEDDING_DIM = 1536
MEMORY_MAX_RESULTS = 20
MEMORY_TEMPORAL_DECAY_DAYS = 30
MEMORY_COMPACTION_THRESHOLD = 1000
MEMORY_COMPACTION_SIMILARITY = 0.85
MEMORY_IMPORTANCE_DECAY_FACTOR = 0.95
MEMORY_ARCHIVE_AFTER_DAYS = 90
MEMORY_BATCH_SIZE = 100
MEMORY_MAX_EXPORT_ENTRIES = 50000
MEMORY_SYNC_DEBOUNCE_MS = 5000

# ── Canales ──────────────────────────────────────────────────
SUPPORTED_CHANNELS = ("telegram", "slack", "discord")

# ── Provider APIs ────────────────────────────────────────────
MODEL_APIS = (
    "anthropic-messages",
    "openai-completions",
    "openai-responses",
    "google-generative-ai",
    "ollama",
    "bedrock-converse-stream",
    "deepseek",
)
