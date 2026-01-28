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
        
        if not getattr(state, "current_user_agent", None):
            try:
                ua = driver.execute_script("return navigator.userAgent;")
                if ua:
                    state.current_user_agent = ua
                    log(f"🕵️ Captured User-Agent: {ua[:30]}...", "INFO")
            except: pass

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

        try:
            csrf = sb.get_attribute('meta[name="csrf-token"]', "content")
            if csrf:
                state.current_csrf_token = csrf
        except: pass
            
    except Exception as e:
        log(f"Token Sync Warning: {e}", "WARN")
        if "connectable" in str(e) or "refused" in str(e) or "process is dead" in str(e):
            raise e

def get_socket_io_creds(bot):
    """Extracts JS variables for WebSocket auth."""
    try:
        sb = bot.sb if hasattr(bot, 'sb') else bot
        html = sb.get_page_source()
        token, user = None, None

        m = re.search(r"io\.connect\('https://ivasms\.com:2087/livesms',\s*\{\s*query\s*:\s*\{\s*token:\s*'([^']+)'[^}]*user:\"([^\"}]+)\"", html, re.DOTALL)
        if m:
            token, user = m.group(1).strip(), m.group(2).strip()

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
    """Performs login with DETAILED DEBUGGING for Cloudflare loops."""
    sb = bot.sb if hasattr(bot, 'sb') else bot
    
    log(f"🌐 Navigating to {config.LOGIN_URL}...", "INFO")
    
    try:
        sb.activate_cdp_mode(config.LOGIN_URL) 
    except:
        try:
            bot.safe_get(config.LOGIN_URL)
        except Exception as e:
            log(f"Navigation error: {e}", "WARN")

    log("⏳ Waiting for Login Page or Captcha...", "INFO")
    
    for i in range(20): 
        # Check success first
        if "portal" in sb.get_current_url() or "live" in sb.get_current_url():
            log("✅ Already logged in!", "OK")
            update_cookies_and_tokens(bot)
            get_socket_io_creds(bot)
            return True

        # Check for Login Form
        if sb.is_element_visible("#card-email"):
            break 

        # Check for Cloudflare
        title = sb.get_title()
        if "Just a moment" in title or sb.is_element_visible('iframe[src*="cloudflare"]'):
            log(f"⚠️ Cloudflare Detected (Attempt {i+1})...", "WARN")
            
            # --- DEBUG LOGGING ---
            try:
                # 1. Verify Visibility
                is_frame = sb.is_element_visible('iframe[src*="cloudflare"]')
                log(f"🔍 Debug: Iframe Visible? {is_frame}", "INFO")
                
                # 2. Dump HTML Snippet (To check for new Challenge types)
                src = sb.get_page_source()
                # Clean up newlines for cleaner log
                snippet = src[:1000].replace("\n", " ").replace("\r", " ")
                log(f"📄 HTML Dump: {snippet}...", "INFO")
                
                # 3. Take Screenshot (If volume mounted, user can check)
                try:
                    path = f"debug_data/cf_debug_{i}.png"
                    sb.save_screenshot(path)
                    log(f"📸 Screenshot saved: {path}", "INFO")
                except: pass
                
            except Exception as e:
                log(f"Debug Logger Error: {e}", "WARN")
            # ---------------------

            # Try to solve
            try:
                sb.uc_gui_click_captcha() 
                log("🖱️ uc_gui_click_captcha() called.", "OK")
            except Exception as e:
                log(f"GUI Click Error: {e}", "WARN")
                # Fallback: Center Click
                sb.execute_script("document.elementFromPoint(window.innerWidth/2, window.innerHeight/2).click();")
        
        time.sleep(3)

    if not sb.is_element_visible("#card-email"):
        log(f"❌ Login form never appeared. URL: {sb.get_current_url()}", "ERROR")
        return False

    log("⌨️ Entering Credentials...", "INFO")
    try:
        sb.type("#card-email", config.IVASMS_EMAIL)
        sb.type("#card-password", config.IVASMS_PASSWORD)
        time.sleep(1)
        
        try:
            bot.smart_click('button[type="submit"]')
        except:
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
