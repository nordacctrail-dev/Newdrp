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
    """Snapshot cookies, tokens, AND User-Agent to RAM."""
    try:
        sb = bot.sb if hasattr(bot, 'sb') else bot
        driver = getattr(bot, "driver", None) or sb.driver
        
        # --- 1. CAPTURE USER-AGENT (CRITICAL for API) ---
        # We need this to make the API requests match the browser
        if not getattr(state, "current_user_agent", None):
            try:
                ua = driver.execute_script("return navigator.userAgent;")
                if ua:
                    state.current_user_agent = ua
                    log(f"🕵️ Captured User-Agent: {ua[:30]}...", "INFO")
            except: pass

        # --- 2. CAPTURE COOKIES (CDP Method) ---
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

        # --- 3. GET CSRF TOKEN ---
        try:
            csrf = sb.get_attribute('meta[name="csrf-token"]', "content")
            if csrf:
                state.current_csrf_token = csrf
        except: pass
            
    except Exception as e:
        log(f"Token Sync Warning: {e}", "WARN")
        # Only crash if driver is truly dead
        if "connectable" in str(e) or "refused" in str(e) or "process is dead" in str(e):
            raise e

def get_socket_io_creds(bot):
    """Extracts JS variables for WebSocket auth."""
    try:
        sb = bot.sb if hasattr(bot, 'sb') else bot
        html = sb.get_page_source()
        token, user = None, None

        # Regex 1
        m = re.search(r"io\.connect\('https://ivasms\.com:2087/livesms',\s*\{\s*query\s*:\s*\{\s*token:\s*'([^']+)'[^}]*user:\"([^\"}]+)\"", html, re.DOTALL)
        if m:
            token, user = m.group(1).strip(), m.group(2).strip()

        # Regex 2 (Fallback)
        if not (token and user):
            m_t = re.search(r"token['\"]?\s*:\s*['\"]([^'\"<>]+)['\"]", html)
            m_u = re.search(r"user['\"]?\s*:\s*['\"]([^'\"<>]+)['\"]", html)
            if m_t and m_u:
                token, user = m_t.group(1).strip(), m_u.group(1).strip()
        
        if token and user:
            state.current_livesms_token = token
            state.current_livesms_user = user
            if getattr(get_socket_io_creds, "last_token", None) != token:
                log(f"🔑 Credentials Found: User={user}", "OK")
                get_socket_io_creds.last_token = token
            return True
    except: pass
    return False

def login_sequence(bot):
    """Performs login using uc_gui_click_captcha for Cloudflare."""
    sb = bot.sb if hasattr(bot, 'sb') else bot
    
    log(f"🌐 Navigating to {config.LOGIN_URL}...", "INFO")
    
    # 1. Navigate
    try:
        sb.activate_cdp_mode(config.LOGIN_URL) # Better than safe_get for anti-detect
    except:
        try:
            bot.safe_get(config.LOGIN_URL)
        except Exception as e:
            log(f"Navigation error: {e}", "WARN")

    # 2. Loop to handle Cloudflare or Login Form
    log("⏳ Waiting for Login Page or Captcha...", "INFO")
    
    for i in range(15): # Loop for ~45 seconds
        # Check success first
        if "portal" in sb.get_current_url() or "live" in sb.get_current_url():
            log("✅ Already logged in!", "OK")
            update_cookies_and_tokens(bot)
            get_socket_io_creds(bot)
            return True

        # Check for Login Form
        if sb.is_element_visible("#card-email"):
            break # Form found! Exit loop and type.

        # Check for Cloudflare
        title = sb.get_title()
        if "Just a moment" in title or sb.is_element_visible('iframe[src*="cloudflare"]'):
            log(f"🤖 Cloudflare Detected (Attempt {i+1})...", "WARN")
            
            # --- THE FIX: Use SeleniumBase's native CAPTCHA clicker ---
            try:
                sb.uc_gui_click_captcha() 
                log("🖱️ Triggered uc_gui_click_captcha()", "OK")
            except Exception as e:
                log(f"GUI Click failed: {e}", "WARN")
                # Fallback: Blind click center
                sb.execute_script("document.elementFromPoint(window.innerWidth/2, window.innerHeight/2).click();")
        
        time.sleep(3)

    # 3. Enter Credentials (only if form exists)
    if not sb.is_element_visible("#card-email"):
        log(f"❌ Login form never appeared. URL: {sb.get_current_url()}", "ERROR")
        return False # Triggers browser restart

    log("⌨️ Entering Credentials...", "INFO")
    try:
        sb.type("#card-email", config.IVASMS_EMAIL)
        sb.type("#card-password", config.IVASMS_PASSWORD)
        time.sleep(1)
        
        # Click Login
        try:
            bot.smart_click('button[type="submit"]')
        except:
            sb.execute_script("document.querySelector('button[type=\"submit\"]').click()")
            
    except Exception as e:
        log(f"Typing failed: {e}", "ERROR")
        return False

    log("⏳ Waiting for Redirect...", "INFO")
    
    # 4. Wait for Dashboard
    for _ in range(30):
        if "portal" in sb.get_current_url() or "live" in sb.get_current_url():
            log("✅ Login Successful!", "OK")
            time.sleep(2)
            update_cookies_and_tokens(bot)
            get_socket_io_creds(bot)
            return True
        time.sleep(1)

    log(f"❌ Login Timeout. URL: {sb.get_current_url()}", "ERROR")
    return False

def browser_thread_target():
    """Main Thread."""
    my_input = HumanInputStrategy()

    while not state.shutdown_event.is_set():
        try:
            log("🚀 Launching Browser Session...", "INFO")
            
            # headless=False is REQUIRED for uc_gui_click_captcha to work
            with StealthBot(headless=False, input_strategy=my_input) as bot:
                state.driver_ref = bot
                sb = bot.sb if hasattr(bot, 'sb') else bot
                try: sb.set_window_size(1920, 1080)
                except: pass
                
                if not login_sequence(bot):
                    send_sync_message("❌ <b>Bot Login Failed - Retrying...</b>")
                    log("🔄 Login failed. Restarting...", "WARN")
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
                        time.sleep(3) 
                        get_socket_io_creds(bot)
                    
                    if "login" in sb.get_current_url():
                        log("⚠️ Session Lost - Re-logging...", "WARN")
                        if not login_sequence(bot):
                            break 

        except Exception as e:
            log(f"💥 Browser Crashed: {e}", "ERROR")
            time.sleep(5)
