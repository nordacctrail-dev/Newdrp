from DrissionPage import ChromiumPage, ChromiumOptions
import time
import json
import os
import utils # Merged Utils
import config
from utils import log
from core.notifier import send_sync_message

# Ensure debug directory exists
if not os.path.exists("debug_data"):
    try:
        os.makedirs("debug_data")
    except: pass

def get_browser():
    """Initializes DrissionPage with anti-detect settings."""
    co = ChromiumOptions()
    
    # Headless settings
    if os.getenv("HEADLESS", "0") == "1":
        co.headless(True)
    else:
        co.headless(False)
    
    co.set_argument('--disable-gpu')
    co.mute(True) 
    
    return ChromiumPage(co)

def update_state(page):
    """Syncs Cookies, Token, and UA to global utils state."""
    try:
        # 1. User Agent
        if not getattr(utils, "current_user_agent", None):
            utils.current_user_agent = page.user_agent
            log(f"🕵️ Captured UA: {utils.current_user_agent[:30]}...", "INFO")

        # 2. Cookies
        cookies_list = page.cookies(as_dict=False)
        simple_cookies = {c['name']: c['value'] for c in cookies_list}
        if simple_cookies:
            utils.current_cookies = simple_cookies

        # 3. CSRF Token
        try:
            meta = page.ele('css:meta[name="csrf-token"]')
            if meta:
                token = meta.attr('content')
                if token:
                    utils.current_csrf_token = token
        except: pass

    except Exception as e:
        log(f"State Sync Error: {e}", "WARN")

def solve_cloudflare(page):
    """Handles 'Just a moment...' check."""
    try:
        title = page.title.lower()
        if "just a moment" in title or "cloudflare" in title:
            log("🛡️ Cloudflare Challenge Detected...", "WARN")
            time.sleep(5)
            page.wait.load_start()
            
            if "just a moment" not in page.title.lower():
                log("✅ Cloudflare Solved!", "OK")
                return True
            else:
                log("⚠️ Still on Cloudflare...", "WARN")
                return False
    except Exception as e:
        log(f"CF Solver Error: {e}", "ERROR")
    return True

def login_sequence(page):
    """Handles Login."""
    try:
        log("🔑 Checking Login...", "INFO")
        page.get(config.LOGIN_URL)
        
        if "login" not in page.url:
            log("✅ Already Logged In", "OK")
            return True

        page.ele('name:email').input(config.IVASMS_EMAIL)
        page.ele('name:password').input(config.IVASMS_PASSWORD)
        page.ele('button[type="submit"]').click()
        page.wait.load_start()
        
        if "login" not in page.url:
            log("✅ Login Successful", "OK")
            return True
        else:
            log("❌ Login Failed", "ERROR")
            return False

    except Exception as e:
        log(f"Login Exception: {e}", "ERROR")
        return False

def browser_thread_target():
    """Main Loop."""
    log("🚀 Starting Browser (DrissionPage)...", "INFO")
    
    page = None
    try:
        page = get_browser()
        
        if not login_sequence(page):
            send_sync_message("❌ <b>Bot Login Failed</b>")
        
        while not utils.shutdown_event.is_set():
            try:
                update_state(page)
                
                # Check for External Signal (e.g. Scanner 403)
                if utils.force_refresh_cookies:
                    log("🚨 Signal: Force Refreshing Cookies...", "WARN")
                    page.get(config.LIVE_SMS_URL)
                    solve_cloudflare(page)
                    update_state(page)
                    utils.force_refresh_cookies = False
                    log("✅ Cookies Refreshed.", "OK")
                    send_sync_message("🔄 <b>Session Refreshed</b>")

                if "login" in page.url:
                    login_sequence(page)

                time.sleep(5)

            except Exception as loop_err:
                log(f"Browser Loop Error: {loop_err}", "ERROR")
                time.sleep(5)

    except Exception as e:
        log(f"💥 Browser Process Crashed: {e}", "ERROR")
    finally:
        if page:
            try: page.quit()
            except: pass
