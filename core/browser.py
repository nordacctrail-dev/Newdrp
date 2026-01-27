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

# Force Docker flags via env vars
os.environ["CHROME_ARGS"] = "--disable-dev-shm-usage --no-sandbox --disable-gpu"
os.environ["GOOGLE_CHROME_ARGS"] = "--disable-dev-shm-usage --no-sandbox --disable-gpu"

def update_cookies_and_tokens(bot):
    """Snapshot cookies and CSRF token to RAM."""
    try:
        # --- COOKIE FETCHING DISABLED (Prevention for Crash) ---
        # driver = getattr(bot, "driver", None)
        # if not driver and hasattr(bot, "sb"):
        #     driver = bot.sb.driver
        #     
        # if driver:
        #     cookies = driver.get_cookies()
        #     simple_cookies = {}
        #     for c in cookies:
        #         if "ivasms" in c.get("domain", "") or "ivasms" in c.get("name", ""):
        #             simple_cookies[c['name']] = c['value']
        #     
        #     if simple_cookies:
        #         state.current_cookies = simple_cookies
        # -------------------------------------------------------

        # 2. Get CSRF Token (Lighter than full cookie fetch)
        sb = bot.sb if hasattr(bot, 'sb') else bot
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

def solve_captcha(sb):
    """
    Checks for and interacts with various Cloudflare/Turnstile CAPTCHAs.
    Returns True if an interaction occurred.
    """
    acted = False
    try:
        # 1. Standard Cloudflare Iframe
        if sb.is_element_visible('iframe[src*="cloudflare"]'):
            log("🤖 Detected Cloudflare Iframe", "WARN")
            sb.switch_to_frame('iframe[src*="cloudflare"]')
            time.sleep(1)
            
            if sb.is_element_visible("#challenge-stage"):
                sb.click("#challenge-stage")
                log("✅ Clicked Cloudflare Challenge Stage", "OK")
                acted = True
            elif sb.is_element_visible('input[type="checkbox"]'):
                sb.click('input[type="checkbox"]')
                log("✅ Clicked Cloudflare Checkbox", "OK")
                acted = True
            elif sb.is_element_visible('.ctp-checkbox-label'):
                sb.click('.ctp-checkbox-label')
                log("✅ Clicked Cloudflare Label", "OK")
                acted = True
                
            sb.switch_to_default_content()
            return acted

        # 2. Generic 'Verify you are human' Checkbox (Non-iframe)
        if sb.is_element_visible('input[type="checkbox"]'):
            sb.click('input[type="checkbox"]')
            log("✅ Clicked Generic Checkbox", "OK")
            return True

        # 3. Cloudflare Turnstile (Shadow DOM wrapper)
        # Sometimes it appears as a widget div
        if sb.is_element_visible('div.cf-turnstile-wrapper'):
            log("🤖 Detected Turnstile Wrapper", "WARN")
            sb.click('div.cf-turnstile-wrapper')
            return True

    except Exception as e:
        log(f"Captcha logic error: {e}", "WARN")
    
    return False

def login_sequence(bot):
    """Performs the full login sequence with robust retry loops."""
    sb = bot.sb if hasattr(bot, 'sb') else bot
    
    log(f"🌐 Navigating to {config.LOGIN_URL}...", "INFO")
    try:
        # Use open instead of safe_get to avoid timeout errors if page loads slowly
        sb.open(config.LOGIN_URL) 
    except Exception as e:
        log(f"Navigation failed: {e}", "ERROR")
        return False
        
    # --- CAPTCHA & FORM DETECTION LOOP ---
    # We loop for up to 60 seconds looking for the form OR a captcha
    log("⏳ Waiting for Login Form or Captcha...", "INFO")
    
    max_retries = 15
    for i in range(max_retries):
        # A. Check if Form is Ready
        if sb.is_element_visible("#card-email"):
            log("✅ Login Form Detected!", "OK")
            break
        
        # B. Check for Captcha
        if solve_captcha(sb):
            log("⏳ Captcha clicked... waiting for reload.", "INFO")
            time.sleep(5) # Give it time to reload the page
            continue
            
        # C. Check if we are already logged in (Redirected fast)
        if "portal" in sb.get_current_url() or "live" in sb.get_current_url():
            log("✅ Already logged in (Session active)", "OK")
            break

        time.sleep(4)
        if i == max_retries - 1:
            log("❌ Login form never appeared.", "ERROR")
            # Log title to see where we are stuck
            log(f"Stuck on Page: {sb.get_title()}", "WARN")
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
        
        # Wait for render (Safety for memory crash)
        time.sleep(15) 
        
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
            
            with StealthBot(headless=True, input_strategy=my_input) as bot:
                state.driver_ref = bot
                sb = bot.sb if hasattr(bot, 'sb') else bot

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
