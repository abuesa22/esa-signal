"""
Telegram bot setup — commands and message sending.
Uses python-telegram-bot v21 (asyncio-based).
"""

import asyncio
import logging
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.constants import ParseMode
from telegram.error import TelegramError

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from database.db import get_stats, get_recent_signals, get_top_signals, update_outcome, save_signal
from database.models import TokenSignal
from bot.formatters import (
    format_signal,
    format_stats,
    format_history,
    format_top_signals,
)
from markets.market_brief import build_morning_brief, build_midday_update, build_evening_brief
from bot.researcher import research

logger = logging.getLogger(__name__)


async def _send(bot: Bot, text: str, chat_id: str = None) -> bool:
    """Send a message, splitting at 4096 chars if needed."""
    cid = chat_id or TELEGRAM_CHAT_ID
    try:
        # Split long messages
        chunk_size = 4096
        for i in range(0, len(text), chunk_size):
            chunk = text[i: i + chunk_size]
            await bot.send_message(
                chat_id=cid,
                text=chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        return True
    except TelegramError as exc:
        logger.error("Telegram send error: %s", exc)
        return False


def send_signal_sync(sig: TokenSignal, bot: Bot):
    """Synchronous wrapper — called from the scanner (non-async context)."""
    signal_id = save_signal(sig)
    sig.id = signal_id
    text = format_signal(sig)
    # Run async send in a new event loop thread-safely
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_send(bot, text))
        else:
            loop.run_until_complete(_send(bot, text))
    except RuntimeError:
        asyncio.run(_send(bot, text))
    logger.info("Signal sent for %s (id=%s, score=%s)", sig.ticker, signal_id, sig.ai_score)


async def send_signal_async(sig: TokenSignal, bot: Bot):
    """Async version for use within async contexts."""
    signal_id = save_signal(sig)
    sig.id = signal_id
    text = format_signal(sig)
    await _send(bot, text)
    logger.info("Signal sent for %s (id=%s, score=%s)", sig.ticker, signal_id, sig.ai_score)


# ── Command handlers ───────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 <b>ESA Signal Bot Online</b>\n\n"
        "<b>Commands:</b>\n"
        "/stats — Win rate and signal stats\n"
        "/history — Last 10 signals\n"
        "/top — Best performing signals\n"
        "/market — Trigger manual market brief\n"
        "/outcome [id] [2x|5x|10x|LOSS|HOLD] — Update a signal outcome\n\n"
        "<b>Research mode:</b>\n"
        "Just type any question — I'll research it live.\n"
        "Examples:\n"
        "• <i>is bitcoin going up today</i>\n"
        "• <i>find coins about trump china</i>\n"
        "• <i>what is trending on solana</i>\n"
        "• <i>[paste a contract address]</i>\n"
        "• <i>what is happening with oil</i>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = get_stats()
    await update.message.reply_text(format_stats(stats), parse_mode=ParseMode.HTML)


async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    signals = get_recent_signals(10)
    await update.message.reply_text(format_history(signals), parse_mode=ParseMode.HTML)


async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    signals = get_top_signals(10)
    await update.message.reply_text(format_top_signals(signals), parse_mode=ParseMode.HTML)


async def cmd_market(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📡 Fetching market data...", parse_mode=ParseMode.HTML)
    try:
        brief = build_evening_brief()
        await _send(ctx.bot, brief, chat_id=str(update.effective_chat.id))
    except Exception as exc:
        logger.error("Manual market brief error: %s", exc)
        await update.message.reply_text(f"⚠️ Error fetching market brief: {exc}")


async def cmd_outcome(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "Usage: /outcome [signal_id] [2x|5x|10x|LOSS|HOLD]"
        )
        return

    try:
        signal_id = int(args[0])
        outcome = args[1].upper()
        valid = {"2x", "5x", "10x", "LOSS", "HOLD"}
        if outcome not in valid:
            await update.message.reply_text(f"Invalid outcome. Use: {', '.join(valid)}")
            return
        update_outcome(signal_id, outcome)
        await update.message.reply_text(
            f"✅ Signal #{signal_id} updated to <b>{outcome}</b>",
            parse_mode=ParseMode.HTML,
        )
    except ValueError:
        await update.message.reply_text("Signal ID must be a number.")
    except Exception as exc:
        logger.error("Outcome update error: %s", exc)
        await update.message.reply_text(f"⚠️ Error: {exc}")


async def cmd_research(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handles any free-text message that is not a command — research chat mode."""
    question = (update.message.text or "").strip()
    if not question:
        return
    cid = str(update.effective_chat.id)
    await update.message.reply_text("🔍 Researching...", parse_mode=ParseMode.HTML)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, research, question)

        # Send coin logo image first if available
        image_url = result.get("image_url")
        if image_url:
            try:
                caption = result.get("caption") or ""
                await ctx.bot.send_photo(
                    chat_id=cid,
                    photo=image_url,
                    caption=caption,
                )
            except Exception as img_exc:
                logger.warning("Could not send research image: %s", img_exc)

        # Send the text analysis
        await _send(ctx.bot, result.get("text", ""), chat_id=cid)

    except Exception as exc:
        logger.error("Research handler error: %s", exc)
        await update.message.reply_text(f"⚠️ Research error: {exc}")


# ── Bot application factory ────────────────────────────────────────────────────

def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("market", cmd_market))
    app.add_handler(CommandHandler("outcome", cmd_outcome))
    # Free-text messages → research mode (must be last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_research))
    return app


# ── Broadcast helpers (called from scheduler) ─────────────────────────────────

async def broadcast_morning(bot: Bot):
    brief = await asyncio.to_thread(build_morning_brief)
    await _send(bot, brief)


async def broadcast_midday(bot: Bot):
    brief = await asyncio.to_thread(build_midday_update)
    await _send(bot, brief)


async def broadcast_evening(bot: Bot):
    brief = await asyncio.to_thread(build_evening_brief)
    await _send(bot, brief)


async def send_startup_notification(bot: Bot):
    await _send(
        bot,
        "🟢 <b>ESA Signal Bot started</b>\n"
        "Crypto scanner active — scanning every 5 min.\n"
        "Scan reports sent after every cycle.\n"
        "Daily briefs: 7am | 12pm | 9pm AEST.\n\n"
        "Commands: /stats /history /top /market",
    )


async def send_error_alert(bot: Bot, message: str):
    await _send(bot, f"🔴 <b>ESA Signal — ERROR</b>\n\n{message}")
