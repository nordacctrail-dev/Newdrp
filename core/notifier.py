import html
import config
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Initialize Bot Instance
bot = Bot(
    token=config.TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

class Notifier:
    @staticmethod
    def format_otp_message(otp_data):
        """
        Formats a raw OTP dictionary using your specific unicode icons.
        """
        originator = html.escape(str(otp_data.get('originator', 'Unknown')))
        recipient = html.escape(str(otp_data.get('recipient', 'Unknown')))
        otp_code = html.escape(str(otp_data.get('otp_code', '---')))
        country = html.escape(str(otp_data.get('country', 'Unknown')))
        message_text = html.escape(str(otp_data.get('message', '')))
        
        # EXACT FORMAT from your uploaded file
        msg = (
            f"櫨 <b>OTP RECEIVED</b>\n\n"
            f"筒 <b>From:</b> <code>{originator}</code>\n"
            f"導 <b>To:</b> <code>{recipient}</code>\n"
            f"柏 <b>Code:</b> <code>{otp_code}</code>\n"
            f"訣 <b>Country:</b> {country}\n\n"
            f"統 <b>Message:</b>\n<i>{message_text}</i>"
        )
        return msg
