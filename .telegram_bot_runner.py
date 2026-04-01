#!/usr/bin/env python3
"""
SOMER Telegram Bot Runner

Auto-restarts on errors with exponential backoff.
"""
import asyncio
import sys
import os
import signal
import time
from pathlib import Path

# =============================================================================
# LOAD ENVIRONMENT VARIABLES
# =============================================================================
project_root = Path("/Users/gabow135/Documents/Proyectos/Somer")
env_path = project_root / ".env"

if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, val = line.split('=', 1)
            os.environ[key.strip()] = val.strip()

print(f"[Bot] TELEGRAM_BOT_TOKEN: {'SET' if os.environ.get('TELEGRAM_BOT_TOKEN') else 'NOT SET'}")
print(f"[Bot] NOTION_API_KEY: {'SET' if os.environ.get('NOTION_API_KEY') else 'NOT SET'}")

# =============================================================================
# PID FILE
# =============================================================================
pid_file = project_root / "logs" / "telegram_bot.pid"
pid_file.parent.mkdir(exist_ok=True)
pid_file.write_text(str(os.getpid()))

running = True

def cleanup(signum=None, frame=None):
    global running
    running = False
    if pid_file.exists():
        pid_file.unlink()
    sys.exit(0)

signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)

# =============================================================================
# MAIN LOOP WITH AUTO-RESTART
# =============================================================================
sys.path.insert(0, str(project_root))

async def run_bot():
    """Run the bot with auto-restart on errors."""
    from tools.telegram import create_telegram_bot

    max_restarts = 10
    restart_count = 0
    base_delay = 5

    while running and restart_count < max_restarts:
        try:
            print(f"[Bot] Starting bot (attempt {restart_count + 1}/{max_restarts})...")
            bot = create_telegram_bot()
            await bot.start()
            print("[Bot] Bot started, entering main loop")

            # Keep running
            while running:
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            print("[Bot] Interrupted by user")
            break

        except Exception as e:
            error_str = str(e)
            restart_count += 1

            if "Conflict" in error_str:
                # Telegram conflict - wait and retry
                delay = base_delay * (2 ** min(restart_count, 5))  # Max 160s
                print(f"[Bot] Conflict detected. Waiting {delay}s before restart...")
                await asyncio.sleep(delay)
            else:
                print(f"[Bot] Error: {error_str}")
                delay = base_delay * restart_count
                print(f"[Bot] Waiting {delay}s before restart...")
                await asyncio.sleep(delay)

        finally:
            try:
                if 'bot' in dir() and bot:
                    await bot.stop()
            except Exception:
                pass

    if restart_count >= max_restarts:
        print(f"[Bot] Max restarts ({max_restarts}) reached. Exiting.")

try:
    asyncio.run(run_bot())
finally:
    cleanup()
