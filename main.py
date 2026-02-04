import asyncio
import logging
import os
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# Import our modular components
import config
from database import Database
from core.worker import IvasmsWorker
from core.notifier import Notifier
from bot_handlers import HandlerMixin
from bot_callbacks import CallbackMixin
from bot_menus import MenuMixin

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

class BotWrapper:
    """
    Helper class to make API calls compatible with our Mixins.
    Wraps the official aiogram Bot instance.
    """
    def __init__(self, token):
        self.real_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    async def get_updates(self, offset, timeout):
        return await self.real_bot.get_updates(offset=offset, timeout=timeout)

    async def api(self, method, data):
        try:
            if method == "sendMessage":
                return await self.real_bot.send_message(**data)
            elif method == "answerCallbackQuery":
                return await self.real_bot.answer_callback_query(**data)
        except Exception as e:
            logging.error(f"API Error ({method}): {e}")

    async def send_to_chat(self, chat_id, text, reply_markup=None):
        try:
            return await self.real_bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        except Exception as e:
            logging.error(f"Send Error: {e}")

    async def edit_msg(self, chat_id, msg_id, text, reply_markup=None):
        try:
            await self.real_bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text, reply_markup=reply_markup)
        except Exception: 
            pass 

    async def delete_msg(self, chat_id, msg_id):
        try: await self.real_bot.delete_message(chat_id, msg_id)
        except: pass

    async def send_file(self, chat_id, file_path, caption=""):
        from aiogram.types import FSInputFile
        try:
            f = FSInputFile(file_path)
            await self.real_bot.send_document(chat_id, f, caption=caption)
        except Exception as e:
            logging.error(f"File Send Error: {e}")

class IvasmsMultiBot(HandlerMixin, CallbackMixin, MenuMixin):
    def __init__(self):
        self.cfg = config
        self.bot = None
        self.db = Database()
        self.workers = {} 

    async def start(self):
        # 1. Initialize Database
        logging.info("💾 Connecting to Database...")
        await self.db.connect()
        
        # 2. Initialize Bot
        self.bot = BotWrapper(self.cfg.TELEGRAM_BOT_TOKEN)
        
        # 3. Restore Accounts from DB
        logging.info("🔄 Restoring Accounts...")
        accounts = await self.db.get_all_accounts()
        
        for acc in accounts:
            await self.spawn_worker(acc['email'], acc['password'])

        if not self.workers:
            logging.warning("⚠️ No accounts loaded. Add one via the Admin Panel.")

        # 4. Start Polling Loop
        logging.info("🚀 Bot Started! Waiting for updates...")
        offset = 0
        while True:
            try:
                updates = await self.bot.get_updates(offset=offset, timeout=20)
                for u in updates:
                    offset = u.update_id + 1
                    u_dict = u.model_dump(exclude_none=True)
                    
                    # Safe Update Handling
                    if u.callback_query:
                        cb = u.callback_query
                        if "message" not in u_dict["callback_query"]: u_dict["callback_query"]["message"] = {}
                        if "chat" not in u_dict["callback_query"]["message"]: u_dict["callback_query"]["message"]["chat"] = {}
                        if "from" not in u_dict["callback_query"]: u_dict["callback_query"]["from"] = {}

                        u_dict["callback_query"]["message"]["chat"]["id"] = cb.message.chat.id
                        u_dict["callback_query"]["message"]["message_id"] = cb.message.message_id
                        u_dict["callback_query"]["from"]["id"] = cb.from_user.id
                        u_dict["callback_query"]["data"] = cb.data
                        u_dict["callback_query"]["id"] = cb.id
                        
                    elif u.message:
                        msg = u.message
                        if "message" not in u_dict: u_dict["message"] = {}
                        if "chat" not in u_dict["message"]: u_dict["message"]["chat"] = {}
                        
                        u_dict["message"]["chat"]["id"] = msg.chat.id
                        
                        if msg.from_user:
                            if "from" not in u_dict["message"]: u_dict["message"]["from"] = {}
                            u_dict["message"]["from"]["id"] = msg.from_user.id
                        
                        u_dict["message"]["text"] = msg.text

                    await self.handle_update(u_dict)
            except Exception as e:
                logging.error(f"Poll Error: {e}")
                await asyncio.sleep(5)

    async def spawn_worker(self, email, password):
        """Creates and starts a new IVASMS Worker."""
        if email in self.workers: return
        
        logging.info(f"👨‍💻 Spawning Worker: {email}")
        worker = IvasmsWorker(email, password, notification_callback=self.distribute_otp)
        self.workers[email] = worker
        
        # Start Worker Services
        asyncio.create_task(worker.start())

    async def kill_worker(self, email):
        """Stops a worker."""
        if email in self.workers:
            logging.info(f"🛑 Stopping Worker: {email}")
            w = self.workers.pop(email)
            w.active = False
            if w.driver:
                try: w.driver.quit()
                except: pass

    async def distribute_otp(self, account_email, otp_data):
        """Broadcasts OTP to allowed users."""
        logging.info(f"🔔 Distributing OTP for {account_email}")
        
        all_users = await self.db.get_all_users()
        recipients = set()
        
        if self.cfg.OWNER_ID != 0:
            recipients.add(self.cfg.OWNER_ID)

        for user in all_users:
            uid = user['chat_id']
            perms = user.get('permissions', [])
            if account_email in perms:
                recipients.add(uid)

        msg_text = Notifier.format_otp_message(otp_data)

        for chat_id in recipients:
            try:
                await self.bot.send_to_chat(chat_id, msg_text)
            except Exception as e:
                logging.error(f"Failed to send OTP to {chat_id}: {e}")

    # ====================================================
    # 🔗 HELPER METHODS (These were missing!)
    # ====================================================
    async def get_visible_emails(self, user_id):
        """Returns list of emails the user is allowed to see."""
        if user_id == self.cfg.OWNER_ID:
            return list(self.workers.keys())
        
        user = await self.db.get_user(user_id)
        if not user: return []
        
        perms = user.get("permissions", [])
        return [e for e in perms if e in self.workers]

    def get_account_alias(self, target_email, visible_emails, user_id, is_admin):
        """Returns a display name for an account."""
        # Owner sees full email
        if user_id == self.cfg.OWNER_ID:
            return target_email
        
        # Admins/Users see "Account 1", "Account 2" for privacy/simplicity
        try:
            sorted_emails = sorted(visible_emails)
            if target_email in sorted_emails:
                index = sorted_emails.index(target_email)
                return f"Account {index + 1}"
            return target_email
        except:
            return "Unknown Account"

if __name__ == "__main__":
    try:
        bot = IvasmsMultiBot()
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        logging.info("👋 Bot Stopped.")
