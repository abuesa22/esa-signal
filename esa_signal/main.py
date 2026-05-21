"""
ESA Signal — main entry point.
Run with: python main.py
"""

import asyncio
import logging
import os
import socket
import sys
import time
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from utils.helpers import setup_logging
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ANTHROPIC_API_KEY
from database.db import init_db
from bot.telegram_bot import build_application, send_startup_notification, send_error_alert
from scheduler import setup_scheduler

setup_logging()
logger = logging.getLogger(__name__)

_PID_FILE = Path(__file__).parent / ".bot.pid"


def _pid_is_running(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        return False


def _acquire_lock():
    """Prevent duplicate bot instances that cause Telegram Conflict errors."""
    if _PID_FILE.exists():
        try:
            old_pid = int(_PID_FILE.read_text().strip())
            if _pid_is_running(old_pid):
                logger.critical(
                    "Bot already running (PID %d) — exiting to prevent Telegram conflict.", old_pid
                )
                sys.exit(1)
            else:
                logger.warning("Stale PID file (PID %d) — overwriting.", old_pid)
        except ValueError:
            pass
    _PID_FILE.write_text(str(os.getpid()))


def _release_lock():
    try:
        _PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _validate_config():
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if missing:
        logger.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)


def _wait_for_network(host="api.telegram.org", port=443, timeout=300):
    """Block until the network is reachable (max 5 minutes). Exits process if it never comes up."""
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((host, port))
            sock.close()
            if attempt > 0:
                logger.info("Network reachable after %d attempt(s)", attempt)
            return
        except OSError:
            attempt += 1
            wait = min(10 * attempt, 60)
            logger.warning("Network not ready (attempt %d) — retrying in %ds...", attempt, wait)
            time.sleep(wait)
    logger.critical("Network unreachable after %ds — exiting", timeout)
    sys.exit(1)


async def main():
    _validate_config()
    _acquire_lock()
    _wait_for_network()

    init_db()

    # Build Telegram application
    app = build_application()
    await app.initialize()
    await app.start()

    bot = app.bot

    # Setup and start scheduler
    scheduler = AsyncIOScheduler()
    setup_scheduler(scheduler, bot)
    scheduler.start()
    logger.info("Scheduler started")

    # Start polling for Telegram commands
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram polling started")

    # Announce startup
    try:
        await send_startup_notification(bot)
    except Exception as exc:
        logger.warning("Startup notification failed: %s", exc)

    logger.info("ESA Signal is live. Press Ctrl+C to stop.")

    # ── Keep alive until interrupted (Windows-compatible) ─────────────────────
    try:
        await asyncio.Event().wait()  # sleep forever — Ctrl+C raises KeyboardInterrupt
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
        pass
    finally:
        logger.info("Shutting down...")
        _release_lock()
        try:
            await send_error_alert(bot, "⚠️ ESA Signal bot is shutting down.")
        except Exception:
            pass
        scheduler.shutdown(wait=False)
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted")
        _release_lock()
    except Exception as exc:
        logger.critical("Fatal error: %s", exc, exc_info=True)
        _release_lock()
        sys.exit(1)
