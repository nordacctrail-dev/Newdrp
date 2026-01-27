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
        # 1. Get CSRF Token (Safe & Fast)
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

def smart_click_captcha(sb):
    """
    Attempts to click the Cloudflare widget using Smart Coordinates
    and Shadow DOM piercing (bypasses standard selectors).
    """
    try:
        log("🖱️ Attempting Smart GUI Click...", "INFO")
        
        # METHOD 1: JS Shadow DOM Pierce (Most Reliable for invisible iframes)
        # Finds the checkbox inside the closed shadow-root of Cloudflare
        sb.execute_script("""
            function clickShadow() {
                let host = document.querySelector('div.cf-turnstile') || document.querySelector('div.cf-turnstile-wrapper');
                if (host && host.shadowRoot) {
                    let btn = host.shadowRoot.querySelector('input') || host.shadowRoot.querySelector('iframe');
                    if (btn) { btn.click(); return true; }
                }
                return false;
            }
            clickShadow();
        """)
        
        # METHOD 2: Center Grid Click (Simulated Human Click)
        # We click 3 points in the vertical center where the box usually is
        # Screen is 1920x1080. Center is (960, 540).
        # We click offsets: Center, Center+40px, Center+80px
        
        # Note: We use JS to synthesize a click at these coords because
        # actions.move_to() can be flaky in headless docker without XVFB.
        
        js_click_coords = """
            function clickAt(x, y) {
                var el = document.elementFromPoint(x, y);
                if (el) el.click();
            }
            clickAt(960, 540);      // Exact Center
            clickAt(960, 580);      // Slightly Lower
            clickAt(960, 500);      // Slightly Higher
        """
        sb.execute_script(js_click_coords)
        log("✅ Fired Smart Grid Clicks (Center Screen)", "OK")
        return True

    except Exception as e:
        log(f"Smart Click Failed: {e}", "WARN")
        return False

def solve_captcha(bot):
    """
    Checks for and interacts with various Cloudflare/Turnstile CAPTCHAs.
    """
    sb = bot.sb if hasattr(bot, 'sb') else bot
    acted = False
    
    try:
        title = sb.get_title()
        
        # --- SCENARIO 1: Cloudflare "Just a moment..." ---
        if "Just a moment" in title or sb.is_element_visible('iframe[src*="cloudflare"]'):
            log("🤖 Cloudflare Challenge Detected", "WARN")
            
            # A. Try Standard Iframe Switch
            if sb.is_element_visible('iframe[src*="cloudflare"]'):
                sb.switch_to_frame('iframe[src*="cloudflare"]')
                time.sleep(0.5)
                if sb.is_element_visible("#challenge-stage"):
                    sb.click("#challenge-stage")
                    acted = True
                elif sb.is_element_visible('input[type="checkbox"]'):
                    sb.click('input[type="checkbox"]')
                    acted = True
                sb.switch_to_default_content()
                
                if acted: 
                    log("✅ Clicked inside Iframe", "OK")
                    return True
            
            # B. If Iframe failed or not found, use SMART CLICK
            log("⚠️ Standard selector failed. Engaging Smart Click...", "WARN")
            return smart_click_captcha(sb)

        # --- SCENARIO 2: Generic Checkbox ---
        if sb.is_element_visible('input[type="checkbox"]'):
            sb.click('input[type="checkbox"]')
            log("✅ Clicked Generic Checkbox", "OK")
            return True

    except Exception as e:
        log(f"Captcha logic error: {e}", "WARN")
    
    return False

def login_sequence(bot):
    """Performs the full login sequence."""
    sb = bot.sb if hasattr(bot, 'sb') else bot
    
    log(f"🌐 Navigating to {config.LOGIN_URL}...", "INFO")
    try:
        sb.open(config.LOGIN_URL) 
    except Exception as e:
        log(f"Navigation failed: {e}", "ERROR")
        return False
        
    log("⏳ Waiting for Login Form or Captcha...", "INFO")
    
    max_retries = 25 
    for i in range(max_retries):
        # A. Check for Form
        if sb.is_element_visible("#card-email"):
            log("✅ Login Form Detected!", "OK")
            break
        
        # B. Check for Captcha / "Just a moment"
        if solve_captcha(bot):
            log("⏳ Captcha interaction... waiting for reload.", "INFO")
            time.sleep(8) 
            continue
            
        # C. Check if already logged in
        if "portal" in sb.get_current_url() or "live" in sb.get_current_url():
            log("✅ Already logged in", "OK")
            break

        time.sleep(3)
        if i == max_retries - 1:
            log("❌ Login form never appeared.", "ERROR")
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
        # Try JS click for reliability
        sb.execute_script("document.querySelector('button[type=\"submit\"]').click()")
    except:
        pass

    log("⏳ Waiting for redirect...", "INFO")
    time.sleep(15)

    # --- CHECK SUCCESS ---
    current_url = sb.get_current_url()
    if "login" not in current_url and ("portal" in current_url or "live" in current_url):
        log("✅ Login Successful!", "OK")
        time.sleep(15) 
        update_cookies_and_tokens(bot)
        get_socket_io_creds(bot)
        return True
    else:
        log(f"❌ Login Failed. URL: {current_url}", "ERROR")
        return False

def browser_thread_target():
    """Main Thread: Auto-restarts browser if it crashes."""
    my_input = HumanInputStrategy()

    while not state.shutdown_event.is_set():
        try:
            log("🚀 Launching Browser Session...", "INFO")
            
            with StealthBot(headless=True, input_strategy=my_input) as bot:
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
