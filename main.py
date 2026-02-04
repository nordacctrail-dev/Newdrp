import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
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
                    
                    # --- FIX: Safe Dictionary Mapping ---
                    if u.callback_query:
                        cb = u.callback_query
                        # Ensure keys exist
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
                        # Ensure keys exist
                        if "message" not in u_dict: u_dict["message"] = {}
                        if "chat" not in u_dict["message"]: u_dict["message"]["chat"] = {}
                        
                        u_dict["message"]["chat"]["id"] = msg.chat.id
                        
                        # SAFE CHECK: Only add 'from' if it exists
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
        
        # Pass the callback for OTP distribution
        worker = IvasmsWorker(email, password, notification_callback=self.distribute_otp)
        self.workers[email] = worker
        
        # Start Worker
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

    # ====================================================
    # 📨 OTP DISTRIBUTOR
    # ====================================================
    async def distribute_otp(self, account_email, otp_data):
        """
        Called by Worker when an OTP arrives.
        Broadcasts it to all users with permission.
        """
        logging.info(f"🔔 Distributing OTP for {account_email}")
        
        # 1. Get all users
        all_users = await self.db.get_all_users()
        recipients = set()
        
        # 2. Always include Owner
        if self.cfg.OWNER_ID != 0:
            recipients.add(self.cfg.OWNER_ID)

        # 3. Check permissions
        for user in all_users:
            uid = user['chat_id']
            perms = user.get('permissions', [])
            if account_email in perms:
                recipients.add(uid)

        # 4. Format Message
        msg_text = Notifier.format_otp_message(otp_data)

        # 5. Send
        for chat_id in recipients:
            try:
                await self.bot.send_to_chat(chat_id, msg_text)
            except Exception as e:
                logging.error(f"Failed to send OTP to {chat_id}: {e}")

if __name__ == "__main__":
    try:
        bot = IvasmsMultiBot()
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        logging.info("👋 Bot Stopped.")
