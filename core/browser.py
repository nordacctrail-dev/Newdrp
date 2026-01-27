import time
import re
import os
import state
import config
from utils import log
from core.notifier import send_sync_message

# Strictly using your stealth wrapper
from sb_stealth_wrapper import StealthBot
from sb_stealth_wrapper.strategies.input import HumanInputStrategy

# 1. Force Headed Mode Env Vars
os.environ["HEADLESS"] = "0"

def update_cookies_and_tokens(bot):
    """Snapshot cookies and CSRF token to RAM."""
    try:
        sb = bot.sb if hasattr(bot, 'sb') else bot
        
        # --- NEW ROBUST COOKIE LOGIC (JS INJECTION) ---
        try:
            # Execute JS to get the full cookie string directly from the browser
            # This is 100% reliable and won't crash the driver
            cookie_str = sb.execute_script("return document.cookie;")
            
            if cookie_str:
                simple_cookies = {}
                # Parse the "key=value; key2=value2" string
                for pair in cookie_str.split(";"):
                    if "=" in pair:
                        k, v = pair.strip().split("=", 1)
                        simple_cookies[k] = v
                
                if simple_cookies:
                    state.current_cookies = simple_cookies
                    # Log once to confirm
                    if not hasattr(update_cookies_and_tokens, "logged"):
                        log(f"🍪 Cookies Synced via JS: {len(simple_cookies)} found", "INFO")
                        update_cookies_and_tokens.logged = True
            else:
                log("⚠️ JS returned empty cookies (Page loading?)", "WARN")

        except Exception as js_err:
            log(f"JS Cookie Fetch Failed: {js_err}", "ERROR")
        # -----------------------------------------------

        # 2. Get CSRF Token
        try:
            csrf = sb.get_attribute('meta[name="csrf-token"]', "content")
            if csrf:
                state.current_csrf_token = csrf
        except:
            pass
            
    except Exception as e:
        log(f"Token Sync Warning: {e}", "WARN")
        if "connectable" in str(e) or "refused" in str(e) or "process is dead" in str(e):
            raise e

def get_socket_io_creds(bot):
    """Extracts JS variables for WebSocket auth."""
    try:
        sb = bot.sb if hasattr(bot, 'sb') else bot
        html = sb.get_page_source()
        token_match = re.search(r"token['\"]?\s*:\s*['\"]([^'\"<>]+)['\"]", html)
        user_match = re.search(r"user['\"]?\s*:\s*['\"]([^'\"<>]+)['\"]", html)
        if token_match and user_match:
            state.current_livesms_token = token_match.group(1)
            state.current_livesms_user = user_match.group(1)
            return True
    except:
        pass
    return False

def login_sequence(bot):
    """Performs login using StealthBot's built-in evasion logic."""
    sb = bot.sb if hasattr(bot, 'sb') else bot
    
    log(f"🌐 Navigating to {config.LOGIN_URL}...", "INFO")
    
    try:
        bot.safe_get(config.LOGIN_URL)
    except Exception as e:
        log(f"Safe Navigation failed: {e}", "ERROR")
        return False

    # Check if we are already logged in
    if "portal" in sb.get_current_url() or "live" in sb.get_current_url():
        log("✅ Already logged in (Session active)", "OK")
        time.sleep(5)
        update_cookies_and_tokens(bot)
        get_socket_io_creds(bot)
        return True

    log("⏳ Waiting for credentials fields...", "INFO")
    try:
        sb.wait_for_element("#card-email", timeout=20)
    except:
        log("❌ Login form not found.", "ERROR")
        return False

    log("⌨️ Entering Credentials...", "INFO")
    try:
        sb.type("#card-email", config.IVASMS_EMAIL)
        sb.type("#card-password", config.IVASMS_PASSWORD)
    except Exception as e:
        log(f"⚠️ Typing Failed: {e}", "WARN")

    log("⌨️ Clicking Login...", "INFO")
    try:
        bot.smart_click('button[type="submit"]')
    except:
        # Fallback to JS click if Human click fails
        sb.execute_script("document.querySelector('button[type=\"submit\"]').click()")

    log("⏳ Waiting for redirect...", "INFO")
    time.sleep(15)

    current_url = sb.get_current_url()
    if "login" not in current_url and ("portal" in current_url or "live" in current_url):
        log("✅ Login Successful!", "OK")
        time.sleep(5) 
        
        # Capture cookies IMMEDIATELY so WS works
        update_cookies_and_tokens(bot)
        get_socket_io_creds(bot)
        return True
    else:
        log(f"❌ Login Failed. URL: {current_url}", "ERROR")
        return False

def browser_thread_target():
    """Main Thread."""
    my_input = HumanInputStrategy()

    while not state.shutdown_event.is_set():
        try:
            log("🚀 Launching Browser Session...", "INFO")
            
            with StealthBot(
                headless=False, # Required for stealth
                input_strategy=my_input,
                success_criteria=None 
            ) as bot:
                
                state.driver_ref = bot
                sb = bot.sb if hasattr(bot, 'sb') else bot

                try: sb.set_window_size(1920, 1080)
                except: pass
                
                if not login_sequence(bot):
                    send_sync_message("❌ <b>Bot Login Failed - Retrying...</b>")
                    log("🔄 Login failed. Restarting browser session in 5s...", "WARN")
                    time.sleep(5)
                    continue 

                send_sync_message("✅ <b>Bot Logged In</b>")
                log("🕵️ Browser entering monitoring loop...", "INFO")
                
                while not state.shutdown_event.is_set():
                    time.sleep(10)
                    # Regularly update cookies to keep WS alive
                    update_cookies_and_tokens(bot)

                    if not state.current_livesms_token:
                        if hasattr(bot, 'safe_get'): bot.safe_get(config.LIVE_SMS_URL)
                        else: sb.open(config.LIVE_SMS_URL)
                        time.sleep(5)
                        get_socket_io_creds(bot)
                    
                    if "login" in sb.get_current_url():
                        log("⚠️ Session Lost - Re-logging...", "WARN")
                        if not login_sequence(bot):
                            break 

        except Exception as e:
            log(f"💥 Browser Crashed: {e}", "ERROR")
            log("🔄 Restarting Browser in 5 seconds...", "INFO")
            time.sleep(5)
