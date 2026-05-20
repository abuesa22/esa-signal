"""Trigger a manual market brief and send it to Telegram."""
import sys
import asyncio
sys.path.insert(0, ".")

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  # noqa: E402
from markets.market_brief import build_evening_brief  # noqa: E402
from telegram import Bot  # noqa: E402
from telegram.constants import ParseMode  # noqa: E402


async def main():
    print("Building market brief...")
    brief = build_evening_brief()
    print(f"Brief built ({len(brief)} chars). Sending to Telegram...")
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    chunk_size = 4096
    for i in range(0, len(brief), chunk_size):
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=brief[i:i + chunk_size],
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    print("Sent.")

asyncio.run(main())
