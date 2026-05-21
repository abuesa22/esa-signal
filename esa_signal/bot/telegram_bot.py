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
from database.db import (
    get_stats, get_recent_signals, get_top_signals, update_outcome,
    save_signal, get_graduation_watchlist,
)
from database.models import TokenSignal
from bot.formatters import (
    format_signal,
    format_stats,
    format_history,
    format_top_signals,
    format_watchlist,
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
        "🤖 <b>ESA Signal Bot</b> — Online\n\n"
        "<b>Signal Commands:</b>\n"
        "/status — Bot health, scan count, last signal\n"
        "/scan — Trigger a manual scan now\n"
        "/stats — Win rate and signal stats\n"
        "/history — Last 10 signals\n"
        "/top — Best performing signals\n"
        "/watchlist — Pump.fun graduation watchlist\n"
        "/market — On-demand market brief\n"
        "/outcome [id] [2x|5x|10x|LOSS|HOLD] — Log a result\n\n"
        "<b>Research mode:</b>\n"
        "Type any question for live AI research:\n"
        "• <i>is bitcoin going up today</i>\n"
        "• <i>find coins about trump china</i>\n"
        "• <i>what is trending on solana</i>\n"
        "• <i>[paste any contract address]</i>",
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


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from scheduler import bot_state
    import time
    uptime_s = int(time.time() - bot_state["start_time"])
    h, rem = divmod(uptime_s, 3600)
    m, s = divmod(rem, 60)
    uptime_str = f"{h}h {m}m {s}s"

    last_signal = "Never"
    if bot_state["last_signal_at"]:
        mins_ago = int((time.time() - bot_state["last_signal_at"]) / 60)
        last_signal = f"{mins_ago}m ago"

    last_scan = "Never"
    if bot_state["last_scan_at"]:
        mins_ago = int((time.time() - bot_state["last_scan_at"]) / 60)
        last_scan = f"{mins_ago}m ago"

    await update.message.reply_text(
        f"📡 <b>ESA Signal — Status</b>\n\n"
        f"⏱ Uptime:         {uptime_str}\n"
        f"🔍 Scans run:      {bot_state['scan_count']}\n"
        f"🪙 Tokens checked: {bot_state['tokens_checked']:,}\n"
        f"🚨 Signals sent:   {bot_state['signals_sent']}\n"
        f"⚠️ Errors:         {bot_state['errors']}\n"
        f"🕐 Last scan:      {last_scan}\n"
        f"📬 Last signal:    {last_signal}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 <b>Manual scan triggered...</b>", parse_mode=ParseMode.HTML)
    try:
        from scanner.crypto_scanner import scan_new_tokens
        from scheduler import bot_state
        import time

        signals_found = []

        def _cb(sig):
            signals_found.append(sig)

        loop = asyncio.get_event_loop()
        tokens_checked, passed = await asyncio.wait_for(
            loop.run_in_executor(None, scan_new_tokens, _cb),
            timeout=240,
        )
        bot_state["scan_count"] += 1
        bot_state["tokens_checked"] += tokens_checked
        bot_state["last_scan_at"] = time.time()

        for sig in signals_found:
            await send_signal_async(sig, ctx.bot)
            bot_state["signals_sent"] += 1
            bot_state["last_signal_at"] = time.time()

        await update.message.reply_text(
            f"✅ <b>Scan complete</b>\n"
            f"Checked: {tokens_checked} tokens\n"
            f"Passed gates: {passed}\n"
            f"Signals sent: {len(signals_found)}",
            parse_mode=ParseMode.HTML,
        )
    except asyncio.TimeoutError:
        await update.message.reply_text("⚠️ Scan timed out after 4 minutes.")
    except Exception as exc:
        logger.error("Manual scan error: %s", exc)
        await update.message.reply_text(f"⚠️ Scan error: {exc}")


async def cmd_watchlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    items = get_graduation_watchlist()
    await update.message.reply_text(
        format_watchlist(items), parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


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
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("market", cmd_market))
    app.add_handler(CommandHandler("outcome", cmd_outcome))
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
    from config import SUPPORTED_CHAINS, SCAN_INTERVAL_MINUTES, MIN_AI_SCORE
    chains = " | ".join(c.upper() for c in SUPPORTED_CHAINS)
    await _send(
        bot,
        f"🟢 <b>ESA Signal Bot — Online</b>\n\n"
        f"Scanning: {chains}\n"
        f"Interval: every {SCAN_INTERVAL_MINUTES} min\n"
        f"AI threshold: {MIN_AI_SCORE}/100\n"
        f"Briefs: 7am | 12pm | 9pm AEST\n\n"
        f"/status /scan /stats /history /watchlist",
    )


async def send_error_alert(bot: Bot, message: str):
    await _send(bot, f"🔴 <b>ESA Signal — ERROR</b>\n\n{message}")
