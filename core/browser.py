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

# Keeps memory safety flags for Docker, even in headed mode
os.environ["CHROME_ARGS"] = "--disable-dev-shm-usage --no-sandbox --disable-gpu"

def update_cookies_and_tokens(bot):
    """Snapshot cookies and CSRF token to RAM."""
    try:
        # 1. Get CSRF Token
        sb = bot.sb if hasattr(bot, 'sb') else bot
        try:
            csrf = sb.get_attribute('meta[name="csrf-token"]', "content")
            if csrf:
                state.current_csrf_token = csrf
        except:
            pass
    except Exception as e:
        log(f"Token Sync Warning: {e}", "WARN")
        # Fatal errors that require restart
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
    """
    Performs login using StealthBot's built-in evasion logic.
    """
    sb = bot.sb if hasattr(bot, 'sb') else bot
    
    log(f"🌐 Navigating to {config.LOGIN_URL}...", "INFO")
    
    # 1. Use safe_get()
    # This automatically waits for body, checks for "Challenge"/"Turnstile", 
    # and auto-solves it using uc_gui_click_captcha.
    try:
        bot.safe_get(config.LOGIN_URL)
    except Exception as e:
        log(f"Safe Navigation failed: {e}", "ERROR")
        return False

    # 2. Check if we are already logged in (Redirected immediately)
    if "portal" in sb.get_current_url() or "live" in sb.get_current_url():
        log("✅ Already logged in (Session active)", "OK")
        time.sleep(5)
        update_cookies_and_tokens(bot)
        get_socket_io_creds(bot)
        return True

    # 3. Wait for Login Form
    log("⏳ Waiting for credentials fields...", "INFO")
    try:
        sb.wait_for_element("#card-email", timeout=20)
    except:
        log("❌ Login form not found (Bot might be stuck on uncaught captcha).", "ERROR")
        return False

    # 4. Enter Credentials
    log("⌨️ Entering Credentials...", "INFO")
    try:
        # Human-like typing is handled by the InputStrategy injected in init
        sb.type("#card-email", config.IVASMS_EMAIL)
        sb.type("#card-password", config.IVASMS_PASSWORD)
    except Exception as e:
        log(f"⚠️ Typing Failed: {e}", "WARN")

    # 5. Smart Click Login
    # Uses 'smart_click' which checks for challenges before clicking 
    # and attempts a human-like click.
    log("⌨️ Clicking Login...", "INFO")
    try:
        bot.smart_click('button[type="submit"]')
    except Exception as e:
        log(f"Smart Click Failed: {e}", "ERROR")
        # Fallback to JS if smart click fails
        sb.execute_script("document.querySelector('button[type=\"submit\"]').click()")

    log("⏳ Waiting for redirect...", "INFO")
    time.sleep(15)

    # 6. Verify Success
    current_url = sb.get_current_url()
    if "login" not in current_url and ("portal" in current_url or "live" in current_url):
        log("✅ Login Successful!", "OK")
        time.sleep(10) # Cooldown for heavy dashboard render
        update_cookies_and_tokens(bot)
        get_socket_io_creds(bot)
        return True
    else:
        log(f"❌ Login Failed. URL: {current_url}", "ERROR")
        return False

def browser_thread_target():
    """
    Main Thread: Auto-restarts browser if it crashes.
    """
    my_input = HumanInputStrategy()

    while not state.shutdown_event.is_set():
        try:
            log("🚀 Launching Browser Session...", "INFO")
            
            # CRITICAL: headless=False per documentation.
            # The wrapper automatically uses Xvfb on Linux servers.
            with StealthBot(
                headless=False, 
                input_strategy=my_input,
                success_criteria=None  # We handle success check manually in login_sequence
            ) as bot:
                
                state.driver_ref = bot
                sb = bot.sb if hasattr(bot, 'sb') else bot

                try: sb.set_window_size(1920, 1080)
                except: pass
                
                # 1. Login
                if not login_sequence(bot):
                    send_sync_message("❌ <b>Bot Login Failed - Retrying...</b>")
                    log("🔄 Login failed. Restarting browser session in 5s...", "WARN")
                    time.sleep(5)
                    continue 

                # 2. Monitor Loop
                send_sync_message("✅ <b>Bot Logged In</b>")
                log("🕵️ Browser entering monitoring loop...", "INFO")
                
                while not state.shutdown_event.is_set():
                    time.sleep(10)
                    update_cookies_and_tokens(bot)

                    if not state.current_livesms_token:
                        # Use safe_get here too for robustness
                        if hasattr(bot, 'safe_get'): 
                            bot.safe_get(config.LIVE_SMS_URL)
                        else: 
                            sb.open(config.LIVE_SMS_URL)
                            
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
