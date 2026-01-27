import time
import threading
import requests
import re

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

    # Shared State for threads (allows the API thread to access browser cookies)
    state = {
        "cookies": {},
        "csrf_token": "",
        "running": True,
        "sms_count": 0
    }

    print("🚀 Starting Bot...")
    telegram.send_message("🚀 **IVASMS Bot Starting**\nMode: Stealth + CDP\nPlatform: Railway/Docker")

    # --- THREAD 1: TELEGRAM LISTENER ---
    # This runs separately so you can click buttons while the browser is busy
    def telegram_listener():
        last_update_id = None
        print("👂 Telegram Listener Started")
        
        while state["running"]:
            try:
                # Poll for updates
                url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/getUpdates"
                params = {"timeout": 10, "offset": last_update_id + 1 if last_update_id else None}
                resp = requests.get(url, params=params, timeout=15).json()

                if not resp.get("ok"):
                    time.sleep(2)
                    continue

                for result in resp.get("result", []):
                    last_update_id = result["update_id"]
                    
                    # --- Handle Callback Queries (Buttons) ---
                    if "callback_query" in result:
                        cb = result["callback_query"]
                        cb_id = cb["id"]
                        data = cb["data"]
                        chat_id = str(cb["message"]["chat"]["id"])
                        
                        # Acknowledge the callback so the loading spinner stops
                        requests.post(f"https://api.telegram.org/bot{config.BOT_TOKEN}/answerCallbackQuery", json={"callback_query_id": cb_id})

                        if chat_id != config.ADMIN_CHAT_ID:
                            continue

                        if data == "menu:status":
                            status_msg = (
                                f"🔧 **System Status**\n"
                                f"Cookies Captured: {len(state['cookies'])}\n"
                                f"CSRF Token: {'✅ Yes' if state['csrf_token'] else '❌ No'}\n"
                                f"SMS Scanned: {state['sms_count']}"
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
                                    # Show first 10 numbers per group to avoid spamming
                                    msg += f"\n**{grp}** ({len(nums)}):\n" + ", ".join(nums[:10])
                                    if len(nums) > 10: msg += "..."
                                telegram.send_message(msg)
                        
                        elif data == "menu:addnum":
                            telegram.send_message("To add a number, reply with:\n`/add 123456`")
                        
                        elif data == "menu:stats":
                            telegram.send_message(f"📊 Total SMS Scanned this session: {state['sms_count']}")

                    # --- Handle Text Messages ---
                    elif "message" in result:
                        msg = result["message"]
                        text = msg.get("text", "")
                        chat_id = str(msg.get("chat", {}).get("id"))

                        if chat_id != config.ADMIN_CHAT_ID:
                            continue

                        if text == "/start" or text == "/menu":
                            telegram.send_message("Welcome! Select an option:", reply_markup=telegram.get_main_menu())
                        
                        elif text.startswith("/add"):
                            parts = text.split()
                            if len(parts) < 2:
                                telegram.send_message("❌ Usage: `/add 123456`")
                            else:
                                term_id = parts[1]
                                telegram.send_message(f"⏳ Adding {term_id}...")
                                success, info = api.add_number(term_id, state["cookies"], state["csrf_token"])
                                if success:
                                    telegram.send_message(f"✅ Success: {info}")
                                else:
                                    telegram.send_message(f"❌ Failed: {info}")

            except Exception as e:
                print(f"Listener Error: {e}")
                time.sleep(5)

    # Start the listener thread
    t_listener = threading.Thread(target=telegram_listener, daemon=True)
    t_listener.start()

    # --- MAIN THREAD: BROWSER LOOP ---
    try:
        # We use the StealthBot wrapper from your Zip file
        # headless=config.HEADLESS ensures it runs on servers like Railway
        with StealthBot(headless=config.HEADLESS) as bot:
            
            # 1. Login Phase
            if not browser_core.login(bot):
                telegram.send_message("❌ Fatal: Login Failed. Shutting down.")
                return

            telegram.send_message("✅ Login Successful. Starting OTP Monitor...")
            
            # Go to the live SMS page
            bot.safe_get(config.LIVE_SMS_URL)
            time.sleep(5)

            while True:
                # 2. Update Session Data (Cookies/CSRF) for the API thread to use
                cookies, csrf, _ = browser_core.get_session_data(bot)
                if cookies: state["cookies"] = cookies
                if csrf: state["csrf_token"] = csrf

                # 3. Check & Solve Cloudflare (using sb.solve_captcha)
                browser_core.handle_cloudflare(bot)

                # 4. Check for Session Loss (Redirects to Login)
                if "login" in bot.driver.current_url:
                    print("⚠️ Session lost. Re-logging...")
                    browser_core.login(bot)
                    bot.safe_get(config.LIVE_SMS_URL)
                    continue

                # 5. Scrape OTPs
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
                    # If we drifted away from the SMS page, go back
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
