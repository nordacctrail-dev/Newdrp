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
        driver = getattr(bot, "driver", None)
        if not driver and hasattr(bot, "sb"):
            driver = bot.sb.driver
            
        if driver:
            # Check if driver is alive before fetching
            if hasattr(driver, "service") and not driver.service.is_connectable():
                raise ConnectionError("Driver is not connectable")

            cookies = driver.get_cookies()
            simple_cookies = {}
            for c in cookies:
                if "ivasms" in c.get("domain", "") or "ivasms" in c.get("name", ""):
                    simple_cookies[c['name']] = c['value']
            
            if simple_cookies:
                state.current_cookies = simple_cookies

        # 2. Get CSRF Token
        sb = bot.sb if hasattr(bot, 'sb') else bot
        try:
            csrf = sb.get_attribute('meta[name="csrf-token"]', "content")
            if csrf:
                state.current_csrf_token = csrf
        except:
            pass
            
    except Exception as e:
        log(f"Cookie Sync Warning: {e}", "WARN")
        # Re-raise if it's a fatal connection error so we can restart the browser
        if "Connection refused" in str(e) or "Max retries exceeded" in str(e) or "not connectable" in str(e):
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
    try:
        bot.safe_get(config.LOGIN_URL)
    except Exception as e:
        log(f"Navigation failed: {e}", "ERROR")
        return False
        
    time.sleep(5)

    # --- CAPTCHA CHECK ---
    log("🛡️ Checking for CAPTCHA...", "INFO")
    try:
        log(f"Current Page Title: {sb.get_title()}", "INFO")
        
        if sb.is_element_visible('iframe[src*="cloudflare"]'):
            log("🤖 Cloudflare iframe detected.", "WARN")
            sb.switch_to_frame('iframe[src*="cloudflare"]')
            time.sleep(1)
            if sb.is_element_visible("#challenge-stage"):
                sb.click("#challenge-stage")
                log("✅ Clicked Cloudflare Challenge", "OK")
            sb.switch_to_default_content()
        elif sb.is_element_visible('input[type="checkbox"]'):
             sb.click('input[type="checkbox"]')
             log("✅ Clicked Generic Captcha", "OK")
    except Exception as e:
        log(f"Captcha check error: {e}", "WARN")

    # --- WAIT FOR FORM ---
    log("⏳ Waiting for login form...", "INFO")
    try:
        sb.wait_for_element("#card-email", timeout=40)
    except:
        log("❌ Login form not found.", "ERROR")
        src = sb.get_page_source()[:500]
        log(f"Page Source Snippet: {src}", "WARN")
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
        sb.execute_script("document.querySelector('button[type=\"submit\"]').click()")

    log("⏳ Waiting for redirect...", "INFO")
    time.sleep(15)

    # --- CHECK SUCCESS ---
    current_url = sb.get_current_url()
    if "login" not in current_url and ("portal" in current_url or "live" in current_url):
        log("✅ Login Successful!", "OK")
        
        # CRITICAL FIX: Give the browser time to settle after redirect before touching cookies
        # This prevents "Connection Refused" if the renderer is still busy swapping pages
        time.sleep(5) 
        
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

    # CRITICAL FIX: Arguments to prevent Docker Crashes
    # We try to pass these to the stealth wrapper.
    # If StealthBot does not accept 'extra_args', try 'browser_args' or remove this argument.
    docker_args = [
        "--no-sandbox",
        "--disable-dev-shm-usage",  # Prevents /dev/shm shared memory crash
        "--disable-gpu",
        "--disable-setuid-sandbox"
    ]
    
    # Format args as a single string if that is what your wrapper expects, 
    # but usually a list or passing them to SB options is best.
    # Assuming StealthBot initializes SeleniumBase, we try to pass arguments via a common param.

    while not state.shutdown_event.is_set():
        try:
            log("🚀 Launching Browser Session...", "INFO")
            
            # ATTEMPT TO PASS ARGS:
            # We are guessing StealthBot accepts kwargs that pass to SB/Driver.
            # If this line errors, you need to edit your sb_stealth_wrapper.py to accept these args.
            with StealthBot(
                headless=True, 
                input_strategy=my_input,
                # Try passing these common SeleniumBase arguments
                binary_location=config.CHROMIUM_BINARY,
                extension_dir=None,
                user_data_dir=None,
                # If your wrapper exposes a way to add args, add them here:
                # args=docker_args 
            ) as bot:
                
                # Manual Injection of Args if wrapper doesn't support them directly
                # (This only works if done BEFORE driver start, which is hard with a Context Manager)
                # So we rely on the wrapper defaults or environment variables.
                
                state.driver_ref = bot
                sb = bot.sb if hasattr(bot, 'sb') else bot

                # Force window size
                try: sb.set_window_size(1920, 1080)
                except: pass
                
                # 1. Try to Login
                if not login_sequence(bot):
                    send_sync_message("❌ <b>Bot Login Failed - Retrying...</b>")
                    log("🔄 Login failed. Restarting browser session in 5s...", "WARN")
                    time.sleep(5)
                    continue 

                # 2. If Login Succeeded, START Monitor
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
                            break # Break inner loop to restart browser

        except Exception as e:
            log(f"💥 Browser Crashed: {e}", "ERROR")
            log("🔄 Restarting Browser in 5 seconds...", "INFO")
            time.sleep(5)
