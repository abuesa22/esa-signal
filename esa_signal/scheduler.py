"""
APScheduler setup.
Runs all timed jobs:
  • Crypto scanner — every 5 minutes
  • Morning brief  — 7:00 AM AEST
  • Midday update  — 12:00 PM AEST
  • Evening brief  — 9:00 PM AEST
"""

import logging
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Bot

from config import SCAN_INTERVAL_MINUTES, TIMEZONE
from scanner.crypto_scanner import scan_new_tokens
from scanner.graduation_watcher import check_graduations
from bot.telegram_bot import (
    broadcast_morning,
    broadcast_midday,
    broadcast_evening,
    send_error_alert,
    _send,
)

logger = logging.getLogger(__name__)
AEST = pytz.timezone(TIMEZONE)

_scan_count = 0


def _make_scan_job(bot: Bot):
    async def _job():
        global _scan_count
        _scan_count += 1
        scan_num = _scan_count
        logger.info("Scan #%d triggered", scan_num)
        try:
            import asyncio
            from bot.telegram_bot import send_signal_async

            loop = asyncio.get_event_loop()
            signals_found = []

            def _callback(sig):
                signals_found.append(sig)

            try:
                tokens_checked, passed = await asyncio.wait_for(
                    loop.run_in_executor(None, scan_new_tokens, _callback),
                    timeout=240,
                )
            except asyncio.TimeoutError:
                logger.error("Scan #%d timed out after 240s — skipping", scan_num)
                await _send(bot, f"⚠️ <b>Scan #{scan_num} timed out</b> — took over 4 min, skipped.")
                return

            signals_sent = 0
            for sig in signals_found:
                try:
                    await send_signal_async(sig, bot)
                    signals_sent += 1
                except Exception as exc:
                    logger.error("Failed to send signal: %s", exc)

            await _send(
                bot,
                f"🔍 <b>Scan #{scan_num} complete</b>\n"
                f"Tokens checked: <b>{tokens_checked}</b> | "
                f"Passed filters: <b>{passed}</b> | "
                f"Signals sent: <b>{signals_sent}</b>",
            )

        except Exception as exc:
            logger.error("Scan job crashed: %s", exc, exc_info=True)
            try:
                await send_error_alert(bot, f"Crypto scanner crashed:\n{exc}")
            except Exception:
                pass

    return _job


def _make_graduation_job(bot: Bot):
    async def _job():
        try:
            import asyncio
            loop = asyncio.get_event_loop()

            alerts: list[str] = []

            def _cb(text: str):
                alerts.append(text)

            await asyncio.wait_for(
                loop.run_in_executor(None, check_graduations, _cb),
                timeout=60,
            )

            for alert in alerts:
                await _send(bot, alert)

        except asyncio.TimeoutError:
            logger.warning("Graduation watcher timed out")
        except Exception as exc:
            logger.error("Graduation watcher crashed: %s", exc, exc_info=True)

    return _job


def _make_brief_job(builder_fn, bot: Bot, name: str):
    async def _job():
        logger.info("%s brief job triggered", name)
        try:
            await builder_fn(bot)
        except Exception as exc:
            logger.error("%s brief crashed: %s", name, exc, exc_info=True)
            try:
                await send_error_alert(bot, f"{name} brief failed:\n{exc}")
            except Exception:
                pass

    return _job


def setup_scheduler(scheduler: AsyncIOScheduler, bot: Bot) -> AsyncIOScheduler:
    scheduler.add_job(
        _make_scan_job(bot),
        trigger=IntervalTrigger(minutes=SCAN_INTERVAL_MINUTES),
        id="crypto_scan",
        name="Crypto Scanner",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        _make_graduation_job(bot),
        trigger=IntervalTrigger(minutes=2),
        id="graduation_watch",
        name="Pump.fun Graduation Watcher",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        _make_brief_job(broadcast_morning, bot, "Morning"),
        trigger=CronTrigger(hour=7, minute=0, timezone=AEST),
        id="morning_brief",
        name="Morning Brief",
        replace_existing=True,
    )

    scheduler.add_job(
        _make_brief_job(broadcast_midday, bot, "Midday"),
        trigger=CronTrigger(hour=12, minute=0, timezone=AEST),
        id="midday_brief",
        name="Midday Update",
        replace_existing=True,
    )

    scheduler.add_job(
        _make_brief_job(broadcast_evening, bot, "Evening"),
        trigger=CronTrigger(hour=21, minute=0, timezone=AEST),
        id="evening_brief",
        name="Evening Brief",
        replace_existing=True,
    )

    logger.info(
        "Scheduler configured: scan every %d min, briefs at 07:00/12:00/21:00 AEST",
        SCAN_INTERVAL_MINUTES,
    )
    return scheduler
