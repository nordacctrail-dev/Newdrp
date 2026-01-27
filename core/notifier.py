import asyncio
import requests # Added for sync sending
import state
import config
from utils import log
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Initialize Bot Instance (Async)
bot = Bot(
    token=config.TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

# --- ASYNC METHODS (For Telegram Poller & WebSocket) ---

async def send_text(chat_id: str, text: str):
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        log(f"Failed to send telegram msg: {e}", "ERROR")

async def send_otp_notification(otp_data: dict):
    chat_id = config.TELEGRAM_ADMIN_CHAT_ID
    if not chat_id: return

    msg = (
        f"🔥 <b>OTP RECEIVED</b>\n\n"
        f"📛 <b>From:</b> <code>{otp_data.get('originator', 'Unknown')}</code>\n"
        f"📱 <b>To:</b> <code>{otp_data.get('recipient', 'Unknown')}</code>\n"
        f"🔐 <b>Code:</b> <code>{otp_data.get('otp_code', '---')}</code>\n"
        f"🌍 <b>Country:</b> {otp_data.get('country', 'Unknown')}\n\n"
        f"📝 <b>Message:</b>\n<i>{otp_data.get('message', '')}</i>"
    )

    try:
        await bot.send_message(chat_id, msg)
    except Exception as e:
        log(f"OTP Send Error: {e}", "ERROR")

# --- SYNC METHODS (For Browser Thread) ---

def send_sync_message(text: str):
    """
    Synchronous fallback using 'requests' to avoid aiogram context errors
    in the browser thread.
    """
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_ADMIN_CHAT_ID
    
    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        log(f"Sync Telegram Failed: {e}", "ERROR")
