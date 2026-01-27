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
        
        # --- SMART JS COOKIE FETCH ---
        try:
            # Execute JS to get cookies without crashing driver
            cookie_str = sb.execute_script("return document.cookie;")
            
            if cookie_str:
                simple_cookies = {}
                for pair in cookie_str.split(";"):
                    if "=" in pair:
                        k, v = pair.strip().split("=", 1)
                        simple_cookies[k] = v
                
                if simple_cookies:
                    state.current_cookies = simple_cookies
                    if not hasattr(update_cookies_and_tokens, "logged"):
                        log(f"🍪 Cookies Synced: {len(simple_cookies)} found", "INFO")
                        update_cookies_and_tokens.logged = True
        except Exception as js_err:
            log(f"JS Cookie Fetch Failed: {js_err}", "ERROR")

        # Get CSRF Token
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
    """Performs login using smart waits instead of sleeps."""
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
        update_cookies_and_tokens(bot)
        get_socket_io_creds(bot)
        return True

    log("⏳ Waiting for credentials fields...", "INFO")
    try:
        # Wait up to 20s for the element, but proceed instantly when found
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
        sb.execute_script("document.querySelector('button[type=\"submit\"]').click()")

    log("⏳ Waiting for Redirect (Max 30s)...", "INFO")
    
    # --- SMART WAIT FOR REDIRECT ---
    # We loop quickly to check URL change instead of sleeping 15s
    start_time = time.time()
    logged_in = False
    
    while time.time() - start_time < 30:
        url = sb.get_current_url()
        if "portal" in url or "live" in url:
            logged_in = True
            break
        # Fast 1s poll
        time.sleep(1)

    if logged_in:
        log("✅ Login Successful!", "OK")
        
        # Capture cookies IMMEDIATELY
        update_cookies_and_tokens(bot)
        get_socket_io_creds(bot)
        return True
    else:
        log(f"❌ Login Timeout. URL: {sb.get_current_url()}", "ERROR")
        return False

def browser_thread_target():
    """Main Thread."""
    my_input = HumanInputStrategy()

    while not state.shutdown_event.is_set():
        try:
            log("🚀 Launching Browser Session...", "INFO")
            
            with StealthBot(
                headless=False,
                input_strategy=my_input,
                success_criteria=None 
            ) as bot:
                
                state.driver_ref = bot
                sb = bot.sb if hasattr(bot, 'sb') else bot

                try: sb.set_window_size(1920, 1080)
                except: pass
                
                if not login_sequence(bot):
                    send_sync_message("❌ <b>Bot Login Failed - Retrying...</b>")
                    log("🔄 Login failed. Retrying...", "WARN")
                    time.sleep(3)
                    continue 

                send_sync_message("✅ <b>Bot Logged In</b>")
                log("🕵️ Browser entering monitoring loop...", "INFO")
                
                while not state.shutdown_event.is_set():
                    # Poll every 10s for token updates
                    time.sleep(10)
                    update_cookies_and_tokens(bot)

                    if not state.current_livesms_token:
                        if hasattr(bot, 'safe_get'): bot.safe_get(config.LIVE_SMS_URL)
                        else: sb.open(config.LIVE_SMS_URL)
                        # Give it a moment to render JS
                        time.sleep(3) 
                        get_socket_io_creds(bot)
                    
                    if "login" in sb.get_current_url():
                        log("⚠️ Session Lost - Re-logging...", "WARN")
                        if not login_sequence(bot):
                            break 

        except Exception as e:
            log(f"💥 Browser Crashed: {e}", "ERROR")
            log("🔄 Restarting Browser in 5 seconds...", "INFO")
            time.sleep(5)
