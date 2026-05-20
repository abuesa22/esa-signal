"""Trigger a manual crypto scan cycle and send any signals to Telegram."""
import sys
import asyncio
import logging
sys.path.insert(0, ".")

from utils.helpers import setup_logging  # noqa: E402
setup_logging()
logger = logging.getLogger(__name__)

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  # noqa: E402
from database.db import init_db, save_signal  # noqa: E402
from scanner.crypto_scanner import scan_new_tokens  # noqa: E402
from bot.formatters import format_signal  # noqa: E402
from telegram import Bot  # noqa: E402
from telegram.constants import ParseMode  # noqa: E402


async def send(bot, text):
    for i in range(0, len(text), 4096):
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text[i:i + 4096],
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def main():
    init_db()
    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    signals_sent = []

    def callback(sig):
        signals_sent.append(sig)

    print("Running scan cycle...")
    await asyncio.to_thread(scan_new_tokens, callback)

    if not signals_sent:
        print("Scan complete — no tokens passed all 4 gates this cycle.")
        await send(bot, "🔍 <b>ESA Signal — Manual Scan Complete</b>\n\nNo tokens passed all 4 gates this cycle.")
        return

    print(f"{len(signals_sent)} signal(s) found — sending to Telegram...")
    for sig in signals_sent:
        sig_id = save_signal(sig)
        sig.id = sig_id
        await send(bot, format_signal(sig))
        print(f"  Sent: ${sig.ticker} [{sig.chain.upper()}] score={sig.ai_score}")

asyncio.run(main())
