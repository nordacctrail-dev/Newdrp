import time
import re
import state
import config
from utils import log
from core.notifier import send_sync_message

# Strictly using your stealth wrapper
from sb_stealth_wrapper import StealthBot
from sb_stealth_wrapper.strategies.input import HumanInputStrategy

def update_cookies_and_tokens(bot):
    """Snapshot cookies and CSRF token to RAM."""
    try:
        # 1. Get Cookies
        # Robust check to find driver in bot or bot.sb
        driver = getattr(bot, "driver", None)
        if not driver and hasattr(bot, "sb"):
            driver = bot.sb.driver
            
        if driver:
            cookies = driver.get_cookies()
            simple_cookies = {}
            for c in cookies:
                # Filter for IVASMS cookies
                if "ivasms" in c.get("domain", "") or "ivasms" in c.get("name", ""):
                    simple_cookies[c['name']] = c['value']
            
            if simple_cookies:
                state.current_cookies = simple_cookies

        # 2. Get CSRF Token
        sb = bot.sb if hasattr(bot, 'sb') else bot
        try:
            # Try getting meta tag
            csrf = sb.get_attribute('meta[name="csrf-token"]', "content")
            if csrf:
                state.current_csrf_token = csrf
        except:
            pass
            
    except Exception as e:
        log(f"Cookie Sync Warning: {e}", "WARN")
        # If connection is refused, this will raise and trigger a restart in the main loop
        if "Connection refused" in str(e) or "Max retries exceeded" in str(e):
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
    """Performs the full login sequence."""
    sb = bot.sb if hasattr(bot, 'sb') else bot
    
    log(f"🌐 Navigating to {config.LOGIN_URL}...", "INFO")
    bot.safe_get(config.LOGIN_URL)
    time.sleep(5)

    # --- CAPTCHA CHECK ---
    log("🛡️ Checking for CAPTCHA...", "INFO")
    try:
        if sb.is_element_visible('iframe[src*="cloudflare"]'):
            sb.switch_to_frame('iframe[src*="cloudflare"]')
            time.sleep(1)
            if sb.is_element_visible("#challenge-stage"):
                sb.click("#challenge-stage")
            sb.switch_to_default_content()
        elif sb.is_element_visible('input[type="checkbox"]'):
             sb.click('input[type="checkbox"]')
             log("✅ Clicked Generic Captcha", "OK")
    except:
        pass

    # --- WAIT FOR FORM ---
    log("⏳ Waiting for login form...", "INFO")
    try:
        sb.wait_for_element("#card-email", timeout=40)
    except:
        log("❌ Login form not found.", "ERROR")
        return False

    # --- TYPING ---
    log("⌨️ Entering Credentials...", "INFO")
    try:
        sb.type("#card-email", config.IVASMS_EMAIL)
        sb.type("#card-password", config.IVASMS_PASSWORD)
    except Exception as e:
        log(f"⚠️ Typing Failed: {e}", "WARN")

    # --- CLICKING ---
    log("⌨️ Clicking Login...", "INFO")
    try:
        submit_selector = 'button[type="submit"]'
        sb.scroll_to(submit_selector)
        time.sleep(0.5)
        sb.click(submit_selector)
    except:
        # JS Fallback
        sb.execute_script("document.querySelector('button[type=\"submit\"]').click()")

    log("⏳ Waiting for redirect...", "INFO")
    time.sleep(15)

    # --- CHECK SUCCESS ---
    current_url = sb.get_current_url()
    if "login" not in current_url and ("portal" in current_url or "live" in current_url):
        log("✅ Login Successful!", "OK")
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

    # Outer loop to restart browser on crash
    while not state.shutdown_event.is_set():
        try:
            log("🚀 Launching Browser Session...", "INFO")
            
            with StealthBot(headless=True, input_strategy=my_input) as bot:
                state.driver_ref = bot
                sb = bot.sb if hasattr(bot, 'sb') else bot

                # Set size
                try: sb.set_window_size(1920, 1080)
                except: pass
                
                # Login
                if login_sequence(bot):
                    send_sync_message("✅ <b>Bot Logged In</b>")
                else:
                    send_sync_message("❌ <b>Bot Login Failed</b>")
                
                # Monitoring Loop
                log("🕵️ Browser entering monitoring loop...", "INFO")
                
                while not state.shutdown_event.is_set():
                    time.sleep(10)
                    
                    # Refresh Cookies (Raises error if driver died)
                    update_cookies_and_tokens(bot)

                    # Refresh Socket Token
                    if not state.current_livesms_token:
                        if hasattr(bot, 'safe_get'): bot.safe_get(config.LIVE_SMS_URL)
                        else: sb.open(config.LIVE_SMS_URL)
                        time.sleep(3)
                        get_socket_io_creds(bot)
                    
                    # Check Session
                    if "login" in sb.get_current_url():
                        log("⚠️ Session Lost - Re-logging...", "WARN")
                        login_sequence(bot)

        except Exception as e:
            log(f"💥 Browser Crashed: {e}", "ERROR")
            log("🔄 Restarting Browser in 5 seconds...", "INFO")
            time.sleep(5)
            # Loop continues -> Restarts StealthBot
