import asyncio
import state
import config
from utils import log
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Initialize Bot Instance
bot = Bot(
    token=config.TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

async def send_text(chat_id: str, text: str):
    """
    Async wrapper to send a simple text message.
    """
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        log(f"Failed to send telegram msg: {e}", "ERROR")

async def send_alert(kind: str, status: str, message: str):
    """
    Sends or updates system alerts (Cloudflare/Session) to the Admin.
    """
    chat_id = config.TELEGRAM_ADMIN_CHAT_ID
    if not chat_id: return

    header = "⚠️ <b>SYSTEM ALERT</b>"
    if kind == "cloudflare": header = "☁️ <b>CLOUDFLARE DETECTED</b>"
    elif kind == "session": header = "🔑 <b>SESSION STATUS</b>"

    color = "🟢" if status == "RESOLVED" else "🔴"
    full_text = f"{header} [{color} {status}]\n\n{message}"

    # Logic to edit existing alert if it exists (avoids spam)
    # Note: For simplicity in this async version, we are just sending new messages
    # unless we track message_ids in state.py (which we do).
    
    prev = state.alert_state.get(kind)
    
    try:
        if prev and prev.get('status') == "ACTIVE" and status == "RESOLVED":
            # Try to edit the previous message to show resolved
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, 
                    message_id=prev['msg_id'], 
                    text=f"{header} [🟢 RESOLVED]\n\n{message}"
                )
                state.alert_state[kind] = None # Clear alert
                return
            except:
                pass # If edit fails, just send new message

        # Send new message
        msg = await bot.send_message(chat_id, full_text)
        
        # Save state if it's an active alert
        if status == "ACTIVE":
            state.alert_state[kind] = {'msg_id': msg.message_id, 'status': "ACTIVE"}
            
    except Exception as e:
        log(f"Alert Error: {e}", "ERROR")

async def send_otp_notification(otp_data: dict):
    """
    Formats and sends an OTP notification.
    """
    chat_id = config.TELEGRAM_ADMIN_CHAT_ID
    if not chat_id: return

    # Format the message
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

# --- SYNC BRIDGE (For Selenium Thread) ---
def send_sync_message(text: str):
    """
    Helper for the blocking Browser thread to send messages 
    without managing its own event loop.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(send_text(config.TELEGRAM_ADMIN_CHAT_ID, text), loop)
        else:
            # Fallback if no loop is found (rare in this setup)
            asyncio.run(send_text(config.TELEGRAM_ADMIN_CHAT_ID, text))
    except:
        pass
