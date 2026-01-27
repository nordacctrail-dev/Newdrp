import time
import os
import re
import config

class BrowserCore:
    def __init__(self):
        self.seen_sms_ids = set()

    def find_screenshot(self, filename):
        """
        Your logic: Hunts for the screenshot in all subfolders.
        """
        search_name = f"{filename}.png"
        if os.path.exists(search_name):
            return search_name
        
        for root, dirs, files in os.walk("."):
            if search_name in files:
                return os.path.join(root, search_name)
        return None

    def login(self, bot):
        """
        Relaxed Login Logic (Trusting StealthBot).
        """
        print(f"🌐 Navigating to {config.LOGIN_URL}")
        bot.safe_get(config.LOGIN_URL)
        
        # 1. THE SIMPLE WAIT (Just like your working script)
        # Trust uc=True to handle the "Just a moment" screen here.
        time.sleep(10)

        # 2. Check if we are already logged in
        if "live/my_sms" in bot.get_current_url() or "portal" in bot.get_current_url():
            print("✅ Session already active.")
            return True

        print("⌨️ Entering credentials...")
        try:
            # 3. Type Credentials directly. 
            # If Cloudflare is still there, this will fail naturally, 
            # and we will catch it in the screenshot.
            bot.type("#card-email", config.EMAIL)
            bot.type("#card-password", config.PASSWORD)
            
            if bot.is_element_visible("#card-checkbox"):
                bot.click("#card-checkbox")

            bot.click('button[type="submit"]')
            
            print("🚀 Login clicked. Waiting for redirect...")
            time.sleep(10)

            if "live/my_sms" in bot.get_current_url() or "portal" in bot.get_current_url():
                print("✅ Login Successful!")
                return True
            else:
                print("❌ Login Failed.")
                bot.save_screenshot("login_failed")
                return False

        except Exception as e:
            print(f"❌ Login Error: {e}")
            
            # 4. CAPTURE & HUNT FOR SCREENSHOT
            try:
                print("📸 Taking crash screenshot...")
                bot.save_screenshot("login_crash")
            except:
                pass
            return False

    def get_session_data(self, bot):
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
                        match = re.search(r'\b\d{4,8}\b', sms['message'])
                        sms['otp'] = match.group(0) if match else "???"
                        new_items.append(sms)
            return new_items
        except:
            return []
