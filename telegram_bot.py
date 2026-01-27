import requests
import config

class TelegramBot:
    """
    Handles sending messages, photos, and managing the Menu UI.
    """
    def __init__(self):
        self.base_url = f"https://api.telegram.org/bot{config.BOT_TOKEN}"
        self.chat_id = config.ADMIN_CHAT_ID

    def _post(self, endpoint, payload):
        try:
            url = f"{self.base_url}/{endpoint}"
            return requests.post(url, json=payload, timeout=10).json()
        except Exception as e:
            print(f"⚠️ Telegram Error ({endpoint}): {e}")
            return {}

    def send_message(self, text, parse_mode="HTML", reply_markup=None):
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._post("sendMessage", payload)

    def send_photo(self, file_path, caption=None):
        """
        Useful for sending screenshots on errors or login success.
        """
        url = f"{self.base_url}/sendPhoto"
        data = {"chat_id": self.chat_id, "caption": caption}
        try:
            with open(file_path, "rb") as f:
                requests.post(url, data=data, files={"photo": f}, timeout=20)
        except Exception as e:
            print(f"⚠️ Telegram Photo Error: {e}")

    def update_status(self, message_id, text):
        """
        Edits a message to show progress (e.g., 'Solving Cloudflare...').
        """
        payload = {
            "chat_id": self.chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML"
        }
        self._post("editMessageText", payload)

    # --- UI KEYBOARDS ---
    def get_main_menu(self):
        return {
            "inline_keyboard": [
                [
                    {"text": "📋 Numbers", "callback_data": "menu:numbers"},
                    {"text": "🔎 Choose Range", "callback_data": "menu:groups"}
                ],
                [
                    {"text": "➕ Add Number", "callback_data": "menu:addnum"},
                    {"text": "🗑 Remove Range", "callback_data": "menu:rmrange"}
                ],
                [
                    {"text": "📊 Stats", "callback_data": "menu:stats"},
                    {"text": "🔧 Status", "callback_data": "menu:status"}
                ]
            ]
        }
