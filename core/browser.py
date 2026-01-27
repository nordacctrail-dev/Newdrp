import time
import re
import state
import config
from utils import log
from core.notifier import send_sync_message

# --- STRICTLY USING YOUR IMPORTS ---
from sb_stealth_wrapper import StealthBot
from sb_stealth_wrapper.strategies.input import HumanInputStrategy

def update_cookies_and_tokens(bot):
    """Snapshot cookies and CSRF token to RAM."""
    try:
        # 1. Get Cookies (StealthBot wraps the driver/sb)
        # Try accessing 'driver' directly or via 'sb'
        driver = getattr(bot, "driver", None)
        if not driver and hasattr(bot, "sb"):
            driver = bot.sb.driver
            
        if driver:
            cookies = driver.get_cookies()
            simple_cookies = {}
            for c in cookies:
                if "ivasms.com" in c.get("domain", "") or "ivasms" in c.get("name", ""):
                    simple_cookies[c['name']] = c['value']
            
            if simple_cookies:
                state.current_cookies = simple_cookies

        # 2. Get CSRF Token
        # Use bot.sb for SeleniumBase methods if available, else driver execute_script
        sb = bot.sb if hasattr(bot, 'sb') else bot
        try:
            csrf = sb.get_attribute('meta[name="csrf-token"]', "content")
            if csrf:
                state.current_csrf_token = csrf
        except:
            pass
    except Exception as e:
        log(f"Cookie Sync Failed: {e}", "ERROR")

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
    Performs the full login sequence using StealthBot logic.
    """
    sb = bot.sb if hasattr(bot, 'sb') else bot
    
    log(f"🌐 Navigating to {config.LOGIN_URL}...", "INFO")
    bot.safe_get(config.LOGIN_URL)
    time.sleep(5)

    # --- CAPTCHA CHECK (Your Logic) ---
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
        log("❌ Login form not found (Stuck on Cloudflare?)", "ERROR")
        return False

    # --- TYPING CREDENTIALS ---
    log("⌨️ Entering Credentials...", "INFO")
    try:
        # Use standard type or smart_type if available on bot
        sb.type("#card-email", config.IVASMS_EMAIL)
        sb.type("#card-password", config.IVASMS_PASSWORD)
    except Exception as e:
        log(f"⚠️ Typing Failed: {e}", "WARN")

    # --- CLICKING LOGIN (Standard Click) ---
    log("⌨️ Clicking Login...", "INFO")
    try:
        submit_selector = 'button[type="submit"]'
        sb.scroll_to(submit_selector)
        time.sleep(0.5)
        sb.click(submit_selector)
    except Exception as e:
        log(f"❌ Click Failed: {e}", "ERROR")
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
    Main Thread: Uses StealthBot Context Manager.
    """
    # 1. Setup Strategy
    my_input = HumanInputStrategy()

    # 2. Launch StealthBot
    # Note: binary_location might need to be passed via kwargs if StealthBot supports it, 
    # or you rely on it finding the system chrome.
    with StealthBot(headless=True, input_strategy=my_input) as bot:
        state.driver_ref = bot # Expose bot ref
        sb = bot.sb if hasattr(bot, 'sb') else bot

        # Set Window Size
        try:
            sb.set_window_size(1920, 1080)
        except:
            pass
        
        # 3. Attempt Login
        if login_sequence(bot):
            send_sync_message("✅ <b>Bot Logged In Successfully</b>")
        else:
            send_sync_message("❌ <b>Bot Login Failed</b>")
        
        # 4. Monitoring Loop
        log("🕵️ Browser entering monitoring loop...", "INFO")
        
        while not state.shutdown_event.is_set():
            time.sleep(10)
            try:
                # Refresh Cookies
                update_cookies_and_tokens(bot)

                # Refresh Socket Token if missing
                if not state.current_livesms_token:
                    # StealthBot usually has safe_get or we use sb.open
                    if hasattr(bot, 'safe_get'):
                        bot.safe_get(config.LIVE_SMS_URL)
                    else:
                        sb.open(config.LIVE_SMS_URL)
                        
                    time.sleep(3)
                    get_socket_io_creds(bot)
                
                # Check Session
                if "login" in sb.get_current_url():
                    log("⚠️ Session Lost - Re-attempting Login...", "WARN")
                    login_sequence(bot)

            except Exception as e:
                log(f"Monitor Loop Error: {e}", "ERROR")
