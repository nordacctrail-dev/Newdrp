import time
import threading
import requests
import re
import os

import config
from stealth_wrapper import StealthBot
from browser_core import BrowserCore
from telegram_bot import TelegramBot
from api_client import IvaApi

def main():
    # Initialize Components
    telegram = TelegramBot()
    browser_core = BrowserCore()
    api = IvaApi()

    # Shared State
    state = {
        "cookies": {},
        "csrf_token": "",
        "running": True,
        "sms_count": 0
    }

    print("🚀 Starting Bot...")
    telegram.send_message("🚀 **IVASMS Bot Starting**\nMode: Stealth + CDP\nPlatform: Railway/Docker")

    # --- THREAD 1: TELEGRAM LISTENER ---
    def telegram_listener():
        last_update_id = None
        print("👂 Telegram Listener Started")
        
        while state["running"]:
            try:
                url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/getUpdates"
                params = {"timeout": 10, "offset": last_update_id + 1 if last_update_id else None}
                resp = requests.get(url, params=params, timeout=15).json()

                if not resp.get("ok"):
                    time.sleep(2)
                    continue

                for result in resp.get("result", []):
                    last_update_id = result["update_id"]
                    
                    if "callback_query" in result:
                        cb = result["callback_query"]
                        cb_id = cb["id"]
                        data = cb["data"]
                        chat_id = str(cb["message"]["chat"]["id"])
                        requests.post(f"https://api.telegram.org/bot{config.BOT_TOKEN}/answerCallbackQuery", json={"callback_query_id": cb_id})

                        if chat_id != config.ADMIN_CHAT_ID: continue

                        if data == "menu:status":
                            status_msg = (
                                f"🔧 **System Status**\n"
                                f"Cookies: {len(state['cookies'])}\n"
                                f"CSRF: {'✅' if state['csrf_token'] else '❌'}\n"
                                f"Scanned: {state['sms_count']}"
                            )
                            telegram.send_message(status_msg)
                        
                        elif data == "menu:numbers":
                            telegram.send_message("📋 Fetching numbers...")
                            groups, _ = api.fetch_numbers(state["cookies"])
                            if not groups:
                                telegram.send_message("⚠️ No numbers found or fetch failed.")
                            else:
                                msg = "📋 **Active Numbers:**\n"
                                for grp, nums in groups.items():
                                    msg += f"\n**{grp}** ({len(nums)}):\n" + ", ".join(nums[:10])
                                    if len(nums) > 10: msg += "..."
                                telegram.send_message(msg)
                        
                        elif data == "menu:addnum":
                            telegram.send_message("To add, reply:\n`/add 123456`")
                        
                        elif data == "menu:stats":
                            telegram.send_message(f"📊 Total SMS: {state['sms_count']}")

                    elif "message" in result:
                        msg = result["message"]
                        text = msg.get("text", "")
                        chat_id = str(msg.get("chat", {}).get("id"))

                        if chat_id != config.ADMIN_CHAT_ID: continue

                        if text == "/start" or text == "/menu":
                            telegram.send_message("Select an option:", reply_markup=telegram.get_main_menu())
                        
                        elif text.startswith("/add"):
                            parts = text.split()
                            if len(parts) < 2:
                                telegram.send_message("❌ Usage: `/add 123456`")
                            else:
                                term_id = parts[1]
                                telegram.send_message(f"⏳ Adding {term_id}...")
                                success, info = api.add_number(term_id, state["cookies"], state["csrf_token"])
                                telegram.send_message(f"✅ Success: {info}" if success else f"❌ Failed: {info}")

            except Exception as e:
                print(f"Listener Error: {e}")
                time.sleep(5)

    t_listener = threading.Thread(target=telegram_listener, daemon=True)
    t_listener.start()

    # --- MAIN THREAD: BROWSER LOOP ---
    try:
        with StealthBot(headless=config.HEADLESS) as bot:
            
            # 1. Login Phase
            if not browser_core.login(bot):
                telegram.send_message("❌ Fatal: Login Failed. Sending debug screenshot...")
                
                # CHECK FOR SCREENSHOT AND SEND IT
                if os.path.exists("login_crash.png"):
                    telegram.send_photo("login_crash.png", caption="❌ Login Crash Screenshot")
                elif os.path.exists("login_failed.png"):
                    telegram.send_photo("login_failed.png", caption="❌ Login Failed Screenshot")
                
                return

            telegram.send_message("✅ Login Successful. Starting Monitor...")
            bot.safe_get(config.LIVE_SMS_URL)
            time.sleep(5)

            while True:
                cookies, csrf, _ = browser_core.get_session_data(bot)
                if cookies: state["cookies"] = cookies
                if csrf: state["csrf_token"] = csrf

                browser_core.handle_cloudflare(bot)

                if "login" in bot.driver.current_url:
                    print("⚠️ Session lost. Re-logging...")
                    browser_core.login(bot)
                    bot.safe_get(config.LIVE_SMS_URL)
                    continue

                if "live/my_sms" in bot.driver.current_url:
                    new_otps = browser_core.scrape_new_otps(bot.driver)
                    if new_otps:
                        state["sms_count"] += len(new_otps)
                        for sms in new_otps:
                            print(f"🔥 OTP Found: {sms['otp']}")
                            msg = (
                                f"📩 **New SMS**\n"
                                f"🔢 Code: `{sms['otp']}`\n"
                                f"👤 Service: {sms['service']}\n"
                                f"🌍 Country: {sms['country']}\n"
                                f"📱 Number: `{sms['number']}`\n"
                                f"💬 Msg: {sms['message'][:100]}"
                            )
                            telegram.send_message(msg)
                else:
                    bot.safe_get(config.LIVE_SMS_URL)

                time.sleep(config.POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n🛑 Stopping...")
    except Exception as e:
        err_msg = f"❌ Crash: {str(e)}"
        print(err_msg)
        telegram.send_message(err_msg)
    finally:
        state["running"] = False
        print("👋 Bye")

if __name__ == "__main__":
    main()
