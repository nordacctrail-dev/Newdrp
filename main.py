import asyncio
import threading
import sys
import state
from utils import log
from core.browser import browser_thread_target
from core.notifier import bot
from core.websocket import websocket_loop
from interface.telegram_bot import router
from aiogram import Dispatcher

async def telegram_poller():
    dp = Dispatcher()
    dp.include_router(router)
    log("🤖 Telegram Poller Started", "INFO")
    await dp.start_polling(bot)

async def main():
    # 1. Start Browser in a Separate Thread (Sync)
    # Selenium is blocking, so we cannot run it in the asyncio loop directly.
    t_browser = threading.Thread(target=browser_thread_target, daemon=True)
    t_browser.start()
    
    # 2. Start WebSocket Loop (Async)
    # This runs concurrently with Telegram
    asyncio.create_task(websocket_loop())
    
    # 3. Start Telegram Poller (Async - Blocking call for main loop)
    await telegram_poller()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        state.shutdown_event.set()
        log("🛑 Bot Stopped", "WARN")
        sys.exit(0)
