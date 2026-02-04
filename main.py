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

    # Generic API caller used by Mixins
    async def api(self, method, data):
        try:
            if method == "sendMessage":
                return await self.real_bot.send_message(**data)
            elif method == "answerCallbackQuery":
                return await self.real_bot.answer_callback_query(**data)
        except Exception as e:
            logging.error(f"API Error ({method}): {e}")

    # Shortcuts used in Mixins
    async def send_to_chat(self, chat_id, text, reply_markup=None):
        return await self.real_bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)

    async def edit_msg(self, chat_id, msg_id, text, reply_markup=None):
        try:
            await self.real_bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text, reply_markup=reply_markup)
        except Exception: 
            pass # Ignore "message is not modified" errors

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
        
        # Worker Registry: { "email@gmail.com": IvasmsWorkerInstance }
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
        if not accounts:
            logging.warning("⚠️ No accounts found in DB. Add one via Admin Panel or Config.")
        
        for acc in accounts:
            await self.spawn_worker(acc['email'], acc['password'])

        # 4. Start Polling Loop
        logging.info("🚀 Bot Started! Waiting for updates...")
        offset = 0
        while True:
            try:
                updates = await self.bot.get_updates(offset=offset, timeout=20)
                for u in updates:
                    offset = u.update_id + 1
                    # Convert Update object to dict for Mixin compatibility
                    u_dict = u.model_dump(exclude_none=True)
                    
                    # aiogram v3 specific mapping
                    if u.callback_query:
                        u_dict["callback_query"]["message"]["chat"]["id"] = u.callback_query.message.chat.id
                        u_dict["callback_query"]["message"]["message_id"] = u.callback_query.message.message_id
                        u_dict["callback_query"]["from"]["id"] = u.callback_query.from_user.id
                        u_dict["callback_query"]["data"] = u.callback_query.data
                        u_dict["callback_query"]["id"] = u.callback_query.id
                    elif u.message:
                        u_dict["message"]["chat"]["id"] = u.message.chat.id
                        u_dict["message"]["from"]["id"] = u.message.from_user.id
                        u_dict["message"]["text"] = u.message.text

                    await self.handle_update(u_dict)
            except Exception as e:
                logging.error(f"Poll Error: {e}")
                await asyncio.sleep(5)

    async def spawn_worker(self, email, password):
        """Creates and starts a new IVASMS Worker."""
        if email in self.workers: return
        
        logging.info(f"👨‍💻 Spawning Worker: {email}")
        worker = IvasmsWorker(email, password)
        self.workers[email] = worker
        
        # Launch Browser in Background
        asyncio.create_task(worker.start_browser())

    async def kill_worker(self, email):
        """Stops a worker and closes its browser."""
        if email in self.workers:
            logging.info(f"🛑 Stopping Worker: {email}")
            w = self.workers.pop(email)
            w.active = False
            if w.driver:
                try: w.driver.quit()
                except: pass

    # Helper: Get aliases for menus
    def get_account_alias(self, target_email, visible_emails, user_id, is_admin):
        if user_id == self.cfg.OWNER_ID:
            return target_email.split('@')[0]
        try:
            sorted_emails = sorted(visible_emails)
            index = sorted_emails.index(target_email)
            return f"Account {index + 1}"
        except ValueError:
            return "Unknown"

    # Helper: Permission Check
    async def get_visible_emails(self, user_id):
        if user_id == self.cfg.OWNER_ID:
            return list(self.workers.keys())
        
        user = await self.db.get_user(user_id)
        if not user: return []
        
        perms = user.get("permissions", [])
        return [e for e in perms if e in self.workers]

if __name__ == "__main__":
    try:
        bot = IvasmsMultiBot()
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        logging.info("👋 Bot Stopped.")
