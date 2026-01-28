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
    """Extracts JS variables for WebSocket auth (Matches t3s.py logic)."""
    try:
        sb = bot.sb if hasattr(bot, 'sb') else bot
        html = sb.get_page_source()
        
        token = None
        user = None

        # 1. Primary Regex (from t3s.py - looks for io.connect call)
        pattern = (
            r"io\.connect\('https://ivasms\.com:2087/livesms',\s*\{\s*query\s*:\s*\{\s*"
            r"token:\s*'([^']+)'[^}]*user:\"([^\"}]+)\""
        )
        m = re.search(pattern, html, re.DOTALL)
        if m:
            token = m.group(1).strip()
            user  = m.group(2).strip()

        # 2. Fallback Regex (Loose search)
        if not (token and user):
            m_token = re.search(r"token['\"]?\s*:\s*['\"]([^'\"<>]+)['\"]", html)
            m_user  = re.search(r"user['\"]?\s*:\s*['\"]([^'\"<>]+)['\"]",  html)
            if m_token and m_user:
                token = token or m_token.group(1).strip()
                user  = user  or m_user.group(1).strip()
        
        if token and user:
            state.current_livesms_token = token
            state.current_livesms_user = user
            log(f"🔑 Credentials Found: User={user}, Token={token[:10]}...", "OK")
            return True
            
    except Exception as e:
        log(f"Creds Extraction Error: {e}", "WARN")
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
    
    # Smart Wait for Redirect
    start_time = time.time()
    logged_in = False
    
    while time.time() - start_time < 30:
        url = sb.get_current_url()
        if "portal" in url or "live" in url:
            logged_in = True
            break
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
                    time.sleep(10)
                    update_cookies_and_tokens(bot)

                    if not state.current_livesms_token:
                        if hasattr(bot, 'safe_get'): bot.safe_get(config.LIVE_SMS_URL)
                        else: sb.open(config.LIVE_SMS_URL)
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
