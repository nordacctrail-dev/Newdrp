import time
import os
import re
import config

class BrowserCore:
    """
    Handles interactions with the browser:
    - Login (With your Stealth setup + Credential Entry)
    - Cloudflare Solving (sb.solve_captcha)
    - OTP Scraping
    """

    def __init__(self):
        self.seen_sms_ids = set()

    def find_screenshot(self, filename):
        """
        Your clever fix: search recursively for the screenshot 
        if Railway saves it in a subfolder.
        """
        if os.path.exists(filename):
            return filename
        
        for root, dirs, files in os.walk("."):
            if filename in files:
                return os.path.join(root, filename)
        return None

    def is_cloudflare(self, bot):
        """Checks if the current page is a Cloudflare challenge."""
        try:
            # Safer check that doesn't crash if driver is busy
            src = bot.get_page_source()
            if not src: return False
            src = src.lower()
            
            if "just a moment" in src: return True
            if "verify you are human" in src: return True
            if "challenge-platform" in src: return True
        except:
            pass
        return False

    def handle_cloudflare(self, bot):
        """
        Uses the wrapper's solve_captcha method.
        """
        if self.is_cloudflare(bot):
            print("🛡️ Cloudflare detected! Attempting sb.solve_captcha()...")
            try:
                if hasattr(bot, "solve_captcha"):
                    bot.solve_captcha()
                time.sleep(config.CLOUDFLARE_WAIT)
            except Exception as e:
                print(f"⚠️ Captcha solve warning: {e}")

    def login(self, bot):
        """
        The FULL Login Phase:
        1. Navigate
        2. Check Cloudflare
        3. Type Credentials (The part your snippet was missing)
        """
        print(f"🌐 Navigating to {config.LOGIN_URL}")
        bot.safe_get(config.LOGIN_URL)
        
        # Initial wait for Railway network
        time.sleep(8)

        # 1. Pre-Login Cloudflare Check
        self.handle_cloudflare(bot)

        # Check if we are already logged in
        if "live/my_sms" in bot.get_current_url() or "portal" in bot.get_current_url():
            print("✅ Session already active.")
            return True

        print("⌨️ Entering credentials...")
        try:
            # 2. Aggressive Cloudflare Re-check if Email input is missing
            if not bot.is_element_visible("#card-email"):
                print("⚠️ Email field not found yet. Checking Cloudflare...")
                self.handle_cloudflare(bot)
                time.sleep(3)

            # 3. Wait for Form (Max 30s)
            print("⏳ Waiting for login form...")
            bot.sb.wait_for_element_visible("#card-email", timeout=30)
            
            # 4. Type Credentials
            bot.type("#card-email", config.EMAIL)
            bot.type("#card-password", config.PASSWORD)
            
            if bot.is_element_visible("#card-checkbox"):
                bot.click("#card-checkbox")

            bot.click('button[type="submit"]')
            
            print("🚀 Login clicked. Waiting for redirect...")
            time.sleep(10)
            self.handle_cloudflare(bot)

            if "live/my_sms" in bot.get_current_url() or "portal" in bot.get_current_url():
                print("✅ Login Successful!")
                return True
            else:
                print("❌ Login Failed.")
                bot.save_screenshot("login_failed.png")
                return False

        except Exception as e:
            print(f"❌ Login Error: {e}")
            
            # 5. Capture Crash Screenshot
            try:
                print("📸 Taking crash screenshot...")
                bot.save_screenshot("login_crash")
            except:
                print("⚠️ Could not take screenshot (Browser died)")
                
            return False

    def get_session_data(self, bot):
        """Extracts Cookies/CSRF for the API thread."""
        cookies = {}
        csrf_token = ""
        user_agent = ""
        try:
            raw_cookies = bot.driver.get_cookies()
            for c in raw_cookies:
                cookies[c['name']] = c['value']

            csrf_token = bot.execute_script("""
                let m = document.querySelector('meta[name="csrf-token"]');
                if (m) return m.content;
                let i = document.querySelector('input[name="_token"]');
                return i ? i.value : "";
            """)
            user_agent = bot.execute_script("return navigator.userAgent;")
        except:
            pass
        return cookies, csrf_token, user_agent

    def scrape_new_otps(self, bot):
        """Scrapes the table for new OTPs."""
        try:
            sms_list = bot.execute_script("""
                let results = [];
                let rows = document.querySelectorAll('table tbody tr');
                rows.forEach(row => {
                    let cols = row.querySelectorAll('td');
                    if (cols.length >= 3) {
                        let service = row.querySelector('.fw-semi-bold.ms-2')?.innerText.trim() || "Unknown";
                        let number = row.querySelector('.CopyText')?.innerText.trim() || "Unknown";
                        let country = row.querySelector('.stretched-link')?.innerText.trim() || "Unknown";
                        let all_text = row.innerText;
                        
                        let msg = "Hidden";
                        let cells = Array.from(cols).map(c => c.innerText.trim());
                        msg = cells.find(c => c.length > 8 && !c.includes(service) && !c.includes(number)) || all_text;

                        let id = number + "|" + service + "|" + msg.substring(0, 15);
                        results.push({ id: id, service: service, number: number, country: country, message: msg });
                    }
                });
                return results;
            """)

            new_items = []
            if sms_list:
                for sms in reversed(sms_list):
                    if sms['id'] not in self.seen_sms_ids:
                        self.seen_sms_ids.add(sms['id'])
                        
                        msg_text = sms['message']
                        otp = "???"
                        match = re.search(r'\b\d{4,8}\b', msg_text)
                        if match: otp = match.group(0)
                        
                        sms['otp'] = otp
                        new_items.append(sms)
            return new_items
        except:
            return []
