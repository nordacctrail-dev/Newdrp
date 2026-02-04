import asyncio
import html
import requests 
import utils  # Merged State + Utils
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

# ===================== ASYNC METHODS =====================
# Used by WebSocket Loop & Main Bot Loop

async def send_text(chat_id: str, text: str):
    """Sends a simple text message asynchronously."""
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        log(f"Failed to send telegram msg: {e}", "ERROR")

async def send_otp_notification(otp_data: dict):
    """Formats and sends an OTP alert asynchronously."""
    chat_id = config.TELEGRAM_ADMIN_CHAT_ID
    if not chat_id: return
    
    # Escape HTML characters to prevent parse errors
    originator = html.escape(str(otp_data.get('originator', 'Unknown')))
    recipient = html.escape(str(otp_data.get('recipient', 'Unknown')))
    otp_code = html.escape(str(otp_data.get('otp_code', '---')))
    country = html.escape(str(otp_data.get('country', 'Unknown')))
    message_text = html.escape(str(otp_data.get('message', '')))
    
    msg = (
        f"📨 <b>OTP RECEIVED</b>\n\n"
        f"🏢 <b>From:</b> <code>{originator}</code>\n"
        f"📱 <b>To:</b> <code>{recipient}</code>\n"
        f"🔑 <b>Code:</b> <code>{otp_code}</code>\n"
        f"🌍 <b>Country:</b> {country}\n\n"
        f"💬 <b>Message:</b>\n<i>{message_text}</i>"
    )

    try:
        await bot.send_message(chat_id, msg)
    except Exception as e:
        log(f"OTP Send Error: {e}", "ERROR")

# ===================== SYNC METHODS =====================
# Used by Browser Thread (Selenium/DrissionPage)

def send_sync_message(text: str):
    """
    Synchronous fallback using 'requests'.
    Required because the browser runs in a separate thread 
    where 'await' logic would fail or block.
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
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        log(f"Sync Msg Error: {e}", "ERROR")
