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
        # Start SB with UC mode enabled for anti-detect features
        self.sb_context = SB(uc=True, headless=self.headless)
        self.sb = self.sb_context.__enter__()
        self.driver = self.sb.driver
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

    def type(self, selector, text):
        """Wrapper for typing text."""
        self.sb.type(selector, text)

    def click(self, selector):
        """Wrapper for clicking elements."""
        self.sb.click(selector)
    
    def is_element_visible(self, selector):
        """Wrapper to check visibility."""
        return self.sb.is_element_visible(selector)
        
    def get_current_url(self):
        """Wrapper to get URL."""
        return self.sb.get_current_url()

    def execute_script(self, script):
        """Wrapper to run JS."""
        return self.sb.execute_script(script)

    def solve_captcha(self):
        """
        Direct wrapper for SeleniumBase's CDP captcha solver.
        This is the method used instead of GUI clicks.
        """
        if hasattr(self.sb, "solve_captcha"):
            print("🤖 Executing sb.solve_captcha()...")
            self.sb.solve_captcha()
        else:
            print("⚠️ Internal SB object does not support solve_captcha")
