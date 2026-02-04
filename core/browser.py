import json
import time
import re
import os
import utils  # CHANGED: Was 'import state'
import config
from utils import log
from core.notifier import send_sync_message

# Strictly using your stealth wrapper
from sb_stealth_wrapper import StealthBot
from sb_stealth_wrapper.strategies.input import HumanInputStrategy

# 1. Force Headed Mode Env Vars
os.environ["HEADLESS"] = "0"

# Ensure debug directory exists
if not os.path.exists("debug_data"):
    try:
        os.makedirs("debug_data")
    except: pass

def update_cookies_and_tokens(bot):
    """Snapshot cookies, tokens, AND User-Agent to RAM."""
    try:
        sb = bot.sb if hasattr(bot, 'sb') else bot
        driver = getattr(bot, "driver", None) or sb.driver
        
        # Capture User-Agent if not already present
        if not getattr(utils, "current_user_agent", None): # CHANGED: utils
            try:
                ua = driver.execute_script("return navigator.userAgent;")
                if ua:
                    utils.current_user_agent = ua # CHANGED: utils
                    log(f"🕵️ Captured User-Agent: {ua[:30]}...", "INFO")
            except: pass

        # Capture Cookies via CDP
        try:
            cookie_data = driver.execute_cdp_cmd('Network.getCookies', {})
            all_cookies = cookie_data.get('cookies', [])
            simple_cookies = {c['name']: c['value'] for c in all_cookies if c.get('name') and c.get('value')}
            
            if simple_cookies:
                utils.current_cookies = simple_cookies # CHANGED: utils
        except:
            # Fallback
            c_list = driver.get_cookies()
            utils.current_cookies = {c['name']: c['value'] for c in c_list} # CHANGED: utils

        # Capture CSRF Token
        try:
            token = driver.execute_script("return document.querySelector('meta[name=\"csrf-token\"]').content")
            if token:
                utils.current_csrf_token = token # CHANGED: utils
        except: pass

    except Exception as e:
        log(f"Cookie Sync Error: {e}", "WARN")

def check_and_solve_cloudflare(bot, target_url):
    """Checks for Cloudflare title and waits."""
    sb = bot.sb if hasattr(bot, 'sb') else bot
    try:
        sb.open(target_url)
        time.sleep(3)
        
        title = sb.get_title()
        if "Just a moment" in title or "Cloudflare" in title:
            log("🛡️ Cloudflare Challenge Detected! Solving...", "WARN")
            time.sleep(10) 
            
            # Additional wait if still blocked
            for _ in range(5):
                if "Just a moment" not in sb.get_title():
                    break
                time.sleep(5)
            log("✅ Cloudflare Passed (hopefully)", "OK")
    except Exception as e:
        log(f"CF Check Error: {e}", "ERROR")

def login_sequence(bot):
    """Performs login if not authenticated."""
    sb = bot.sb if hasattr(bot, 'sb') else bot
    
    try:
        log("🔑 Starting Login Sequence...", "INFO")
        sb.open(config.LOGIN_URL)
        time.sleep(5)
        
        # Check if already logged in (redirected to dashboard/portal)
        if "login" not in sb.get_current_url():
            log("✅ Already Logged In", "OK")
            return True

        # Type Email
        sb.type('input[name="email"]', config.IVASMS_EMAIL)
        time.sleep(1)
        
        # Type Password
        sb.type('input[name="password"]', config.IVASMS_PASSWORD)
        time.sleep(1)
        
        # Click Login
        sb.click('button[type="submit"]')
        time.sleep(5)
        
        # Verify
        if "login" not in sb.get_current_url():
            log("✅ Login Successful", "OK")
            return True
        else:
            log("❌ Login Failed (Still on login page)", "ERROR")
            return False
            
    except Exception as e:
        log(f"Login Error: {e}", "ERROR")
        return False

def browser_thread_target():
    """Main Browser Loop."""
    log("🚀 Starting Browser Thread...", "INFO")
    
    while not utils.shutdown_event.is_set(): # CHANGED: utils
        try:
            with StealthBot(headed=True) as bot:
                sb = bot.sb if hasattr(bot, 'sb') else bot
                try: sb.set_window_size(1920, 1080)
                except: pass
                
                if not login_sequence(bot):
                    send_sync_message("❌ <b>Bot Login Failed - Retrying...</b>")
                    time.sleep(5)
                    continue 

                while not utils.shutdown_event.is_set(): # CHANGED: utils
                    time.sleep(5)
                    update_cookies_and_tokens(bot)

                    # --- CRITICAL FIX: WATCH FOR SIGNAL FROM API/WS ---
                    if utils.force_refresh_cookies: # CHANGED: utils
                        log("🚨 API/WS reported 403 - Solving Cloudflare...", "WARN")
                        # Go to LIVE SMS to clear path for WebSocket credentials
                        check_and_solve_cloudflare(bot, config.LIVE_SMS_URL)
                        update_cookies_and_tokens(bot)
                        
                        utils.force_refresh_cookies = False # CHANGED: utils
                        log("✅ Browser cleared Cloudflare.", "OK")
                        
                        cookie_json = json.dumps(utils.current_cookies, indent=2) # CHANGED: utils
                        send_sync_message(f"🔄 <b>Cloudflare Solved !</b>\n<pre>{cookie_json}</pre>")

                    # Auto-Relogin check
                    if "login" in sb.get_current_url():
                        if not login_sequence(bot): break 

        except Exception as e:
            log(f"💥 Browser Crashed: {e}", "ERROR")
            time.sleep(5)
