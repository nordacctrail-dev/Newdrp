import time
import threading
import requests
import re
import os

import config
from sb_stealth_wrapper import StealthBot  # Renamed import
from browser_core import BrowserCore
from telegram_bot import TelegramBot
from api_client import IvaApi

def main():
    telegram = TelegramBot()
    browser_core = BrowserCore()
    api = IvaApi()

    state = {"cookies": {}, "csrf_token": "", "running": True, "sms_count": 0}

    print("🚀 Starting Bot (Stealth Mode)...")
    telegram.send_message("🚀 **IVASMS Bot Starting**")

    # --- LISTENER THREAD (Keep as is) ---
    def telegram_listener():
        last_update_id = None
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
                    if "message" in result:
                        msg = result["message"]
                        text = msg.get("text", "")
                        chat_id = str(msg.get("chat", {}).get("id"))
                        if chat_id != config.ADMIN_CHAT_ID: continue

                        if text == "/start": telegram.send_message("Menu:", reply_markup=telegram.get_main_menu())
                        elif text.startswith("/add"):
                            parts = text.split()
                            if len(parts) > 1:
                                success, info = api.add_number(parts[1], state["cookies"], state["csrf_token"])
                                telegram.send_message(f"✅ {info}" if success else f"❌ {info}")
            except:
                time.sleep(5)

    t_listener = threading.Thread(target=telegram_listener, daemon=True)
    t_listener.start()

    # --- MAIN BROWSER LOOP ---
    try:
        with StealthBot(headless=config.HEADLESS) as bot:
            
            # 1. Login Phase (Now simpler)
            if not browser_core.login(bot):
                telegram.send_message("❌ Fatal: Login Failed. Searching for proof...")
                
                # Use recursive finder from browser_core
                crash_pic = browser_core.find_screenshot("login_crash")
                fail_pic = browser_core.find_screenshot("login_failed")
                
                if crash_pic: telegram.send_photo(crash_pic, "❌ Crash Evidence")
                elif fail_pic: telegram.send_photo(fail_pic, "❌ Failure Evidence")
                else: telegram.send_message("⚠️ No screenshot found.")
                
                return

            telegram.send_message("✅ Login Successful. Watching for OTPs...")
            bot.safe_get(config.LIVE_SMS_URL)
            time.sleep(5)

            while True:
                # Update Session
                cookies, csrf, _ = browser_core.get_session_data(bot)
                if cookies: state["cookies"] = cookies
                if csrf: state["csrf_token"] = csrf

                # Scrape
                if "live/my_sms" in bot.get_current_url():
                    new_otps = browser_core.scrape_new_otps(bot) # Pass bot, not driver
                    if new_otps:
                        state["sms_count"] += len(new_otps)
                        for sms in new_otps:
                            telegram.send_message(f"🔥 **OTP:** `{sms['otp']}`\nService: {sms['service']}")
                else:
                    bot.safe_get(config.LIVE_SMS_URL)

                time.sleep(config.POLL_INTERVAL)

    except KeyboardInterrupt:
        print("Stopping...")
    except Exception as e:
        telegram.send_message(f"❌ Main Loop Crash: {e}")
    finally:
        state["running"] = False

if __name__ == "__main__":
    main()
