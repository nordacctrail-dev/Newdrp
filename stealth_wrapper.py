import time
from seleniumbase import SB

class StealthBot:
    """
    Wrapper for SeleniumBase to run in a stealthy context.
    """
    def __init__(self, headless=True):
        self.headless = headless
        self.sb = None
        self.driver = None

    def __enter__(self):
        # uc=True enables Undetected Chromedriver (The core Stealth feature)
        # We add extra arguments to help bypass Cloudflare on Railway
        self.sb_context = SB(
            uc=True, 
            headless=self.headless,
            browser="chrome",
            # Force a standard resolution to prevent "Headless" dimension detection
            agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            block_images=True,  # Saves bandwidth, speeds up load
        )
        self.sb = self.sb_context.__enter__()
        self.driver = self.sb.driver
        
        # Explicitly set window size (Fixes many headless detection scripts)
        self.driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {
            "width": 1920,
            "height": 1080,
            "deviceScaleFactor": 1,
            "mobile": False
        })
        
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.sb_context.__exit__(exc_type, exc_val, exc_tb)

    def safe_get(self, url):
        """Navigate to a URL with error handling."""
        try:
            self.sb.open(url)
        except Exception as e:
            print(f"⚠️ Navigation warning: {e}")

    def save_screenshot(self, name):
        """Save screenshot helper."""
        try:
            self.sb.save_screenshot(f"{name}.png")
        except Exception as e:
            print(f"⚠️ Screenshot failed: {e}")

    def get_page_source(self):
        """Wrapper to get page source safely."""
        try:
            return self.sb.get_page_source()
        except:
            return ""

    def type(self, selector, text):
        self.sb.type(selector, text)

    def click(self, selector):
        self.sb.click(selector)
    
    def is_element_visible(self, selector):
        return self.sb.is_element_visible(selector)
        
    def get_current_url(self):
        return self.sb.get_current_url()

    def execute_script(self, script):
        return self.sb.execute_script(script)

    def solve_captcha(self):
        """
        Direct wrapper for SeleniumBase's CDP captcha solver.
        """
        if hasattr(self.sb, "solve_captcha"):
            print("🤖 Executing sb.solve_captcha()...")
            self.sb.solve_captcha()
        else:
            print("⚠️ Internal SB object does not support solve_captcha")
