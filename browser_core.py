import time
import re
import config

class BrowserCore:
    """
    Handles interactions with the browser:
    - Login
    - Cloudflare Solving (Using sb.solve_captcha)
    - OTP Scraping
    """

    def __init__(self):
        self.seen_sms_ids = set()

    def is_cloudflare(self, bot):
        """Checks if the current page is a Cloudflare challenge."""
        try:
            title = bot.driver.title.lower()
            src = bot.driver.page_source.lower()
            if "just a moment" in title or "verify you are human" in src or "challenge" in src:
                return True
        except:
            pass
        return False

    def handle_cloudflare(self, bot):
        """
        Uses the wrapper's solve_captcha method (CDP based).
        """
        if self.is_cloudflare(bot):
            print("🛡️ Cloudflare detected!")
            try:
                if hasattr(bot, "solve_captcha"):
                    bot.solve_captcha()
                time.sleep(config.CLOUDFLARE_WAIT)
            except Exception as e:
                print(f"⚠️ Captcha solve warning: {e}")

    def login(self, bot):
        """
        Performs the login flow with increased timeouts and debug screenshots.
        """
        print(f"🌐 Navigating to {config.LOGIN_URL}")
        bot.safe_get(config.LOGIN_URL)
        
        # Increased initial wait for Railway
        time.sleep(10)

        self.handle_cloudflare(bot)

        # Check if we are already logged in
        if "live/my_sms" in bot.get_current_url() or "portal" in bot.get_current_url():
            print("✅ Session already active.")
            return True

        print("⌨️ Entering credentials...")
        try:
            # CRITICAL FIX: Explicit wait up to 30 seconds for the form
            print("⏳ Waiting for login form (max 30s)...")
            bot.sb.wait_for_element_visible("#card-email", timeout=30)
            
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
                bot.save_screenshot("login_failed")
                return False

        except Exception as e:
            print(f"❌ Login Exception: {e}")
            # CAPTURE SCREENSHOT ON CRASH
            print(f"📸 Taking debug screenshot: login_crash.png")
            print(f"Current Page Title: {bot.driver.title}")
            bot.save_screenshot("login_crash")
            return False

    def get_session_data(self, bot):
        """
        Extracts Cookies and CSRF token for the API Client.
        """
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

        except Exception as e:
            print(f"⚠️ Failed to extract session data: {e}")

        return cookies, csrf_token, user_agent

    def scrape_new_otps(self, bot):
        """
        Injects JS to read the table and returns NEW messages only.
        """
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
                        
                        results.push({
                            id: id,
                            service: service,
                            number: number,
                            country: country,
                            message: msg
                        });
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
                        if match:
                            otp = match.group(0)
                        
                        sms['otp'] = otp
                        new_items.append(sms)
                        
            return new_items

        except Exception as e:
            return []
