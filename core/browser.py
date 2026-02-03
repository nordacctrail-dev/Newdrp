import json
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
        if not getattr(state, "current_user_agent", None):
            try:
                ua = driver.execute_script("return navigator.userAgent;")
                if ua:
                    state.current_user_agent = ua
                    log(f"🕵️ Captured User-Agent: {ua[:30]}...", "INFO")
            except: pass

        # Capture Cookies via CDP
        try:
            cookie_data = driver.execute_cdp_cmd('Network.getCookies', {})
            all_cookies = cookie_data.get('cookies', [])
            simple_cookies = {c['name']: c['value'] for c in all_cookies if c.get('name') and c.get('value')}
            
            if simple_cookies:
                state.current_cookies = simple_cookies
                if not hasattr(update_cookies_and_tokens, "logged"):
                    log(f"🍪 Cookies Synced ({len(simple_cookies)})", "INFO")
                    update_cookies_and_tokens.logged = True
        except: pass

        # Capture CSRF
        try:
            csrf = sb.get_attribute('meta[name="csrf-token"]', "content")
            if csrf:
                state.current_csrf_token = csrf
        except: pass
            
    except Exception as e:
        log(f"Token Sync Warning: {e}", "WARN")

def check_and_solve_cloudflare(bot, url=None):
    """Checks for Cloudflare and solves it if present."""
    sb = bot.sb if hasattr(bot, 'sb') else bot
    
    if url:
        try:
            sb.activate_cdp_mode(url)
            sb.sleep(2)
        except: pass

    title = sb.get_title()
    if "Just a moment" in title or sb.is_element_visible('iframe[src*="cloudflare"]'):
        log("🛡️ Cloudflare Detected - Solving...", "WARN")
        
        try:
            if hasattr(sb, "uc_gui_click_captcha"):
                sb.solve_captcha()
        except: pass
        
        sb.sleep(2)
        
        if "Just a moment" in sb.get_title():
            try:
                if hasattr(sb, "solve_captcha"):
                    sb.solve_captcha()
            except: pass

        if "Just a moment" in sb.get_title():
            try:
                 sb.execute_script("document.elementFromPoint(window.innerWidth/2, window.innerHeight/2).click();")
            except: pass
        
        sb.sleep(2)
        return True
    return False

def login_sequence(bot):
    """Performs login and sends full session JSON once."""
    sb = bot.sb if hasattr(bot, 'sb') else bot
    
    log(f"🌐 Navigating to {config.LOGIN_URL}...", "INFO")
    check_and_solve_cloudflare(bot, config.LOGIN_URL)

    # SUCCESS: Already in
    if "portal" in sb.get_current_url() or "live" in sb.get_current_url():
        log("✅ Already logged in!", "OK")
        update_cookies_and_tokens(bot)
        
        # Send JSON with Cookies + UA
        payload = {
            "user_agent": getattr(state, "current_user_agent", "Not Captured"),
            "cookies": state.current_cookies
        }
        send_sync_message(f"✅ <b>Session Resumed</b>\n<pre>{json.dumps(payload, indent=2)}</pre>")
        return True

    if not sb.is_element_visible("#card-email"):
        sb.sleep(2)
        if not sb.is_element_visible("#card-email"):
            return False

    log("⌨️ Entering Credentials...", "INFO")
    try:
        sb.type("#card-email", config.IVASMS_EMAIL)
        sb.type("#card-password", config.IVASMS_PASSWORD)
        time.sleep(1)
        sb.execute_script("document.querySelector('button[type=\"submit\"]').click()")
    except Exception as e:
        log(f"Typing failed: {e}", "ERROR")
        return False

    log("⏳ Waiting for Redirect...", "INFO")
    for _ in range(30):
        if "portal" in sb.get_current_url() or "live" in sb.get_current_url():
            log("✅ Login Successful!", "OK")
            time.sleep(2)
            update_cookies_and_tokens(bot)
            
            cookie_json = json.dumps(state.current_cookies, indent=2)
                        send_sync_message(f"✅ <b>Login Successful! </b>\n<pre>{cookie_json}</pre>")
            return True
        time.sleep(1)
    return False

def browser_thread_target():
    """Main Thread Handling solving and syncing."""
    my_input = HumanInputStrategy()

    while not state.shutdown_event.is_set():
        try:
            log("🚀 Launching Browser Session...", "INFO")
            
            with StealthBot(headless=False, input_strategy=my_input) as bot:
                state.driver_ref = bot
                sb = bot.sb if hasattr(bot, 'sb') else bot
                try: sb.set_window_size(1920, 1080)
                except: pass
                
                if not login_sequence(bot):
                    send_sync_message("❌ <b>Bot Login Failed - Retrying...</b>")
                    time.sleep(5)
                    continue 

                while not state.shutdown_event.is_set():
                    time.sleep(5)
                    update_cookies_and_tokens(bot)

                    # --- CRITICAL FIX: WATCH FOR SIGNAL FROM API/WS ---
                    if state.force_refresh_cookies:
                        log("🚨 API/WS reported 403 - Solving Cloudflare...", "WARN")
                        # Go to LIVE SMS to clear path for WebSocket credentials
                        check_and_solve_cloudflare(bot, config.LIVE_SMS_URL)
                        update_cookies_and_tokens(bot)
                        
                        state.force_refresh_cookies = False
                        log("✅ Browser cleared Cloudflare.", "OK")
                        
                        cookie_json = json.dumps(state.current_cookies, indent=2)
                        send_sync_message(f"🔄 <b>Cloudflare Solved !</b>\n<pre>{cookie_json}</pre>")

                    # Auto-Relogin check
                    if "login" in sb.get_current_url():
                        if not login_sequence(bot): break 

        except Exception as e:
            log(f"💥 Browser Crashed: {e}", "ERROR")
            time.sleep(5)