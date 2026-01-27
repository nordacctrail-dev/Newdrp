import time
from seleniumbase import SB

class StealthBot:
    """
    Wrapper for SeleniumBase to run in a stealthy context.
    Matches the logic of your working 'newex.zip' script.
    """
    def __init__(self, headless=True):
        self.headless = headless
        self.sb = None
        self.driver = None

    def __enter__(self):
        # uc=True is the magic switch that bypasses Cloudflare
        self.sb_context = SB(uc=True, headless=self.headless)
        self.sb = self.sb_context.__enter__()
        self.driver = self.sb.driver
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.sb_context.__exit__(exc_type, exc_val, exc_tb)

    def safe_get(self, url):
        try:
            self.sb.open(url)
        except Exception as e:
            print(f"⚠️ Navigation warning: {e}")

    def save_screenshot(self, name):
        try:
            self.sb.save_screenshot(f"{name}.png")
        except Exception as e:
            print(f"⚠️ Screenshot failed: {e}")
            
    # Add simple wrappers for interactions
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
