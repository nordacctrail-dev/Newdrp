import os

# ===================== RAILWAY / DOCKER CONFIG =====================
# Default binary path for standard Docker/Railway containers.
# If running locally on Termux, you might need "/data/data/com.termux/files/usr/bin/chromium-browser"
CHROMIUM_BINARY = os.getenv("CHROMIUM_BINARY", "/usr/bin/google-chrome")

# ===================== CREDENTIALS =====================
# 1. Tries to read from Railway "Variables" first (More Secure).
# 2. Falls back to the hardcoded strings if no variable is found.
IVASMS_EMAIL = os.getenv("IVASMS_EMAIL", "siamkushtia33@gmail.com")
IVASMS_PASSWORD = os.getenv("IVASMS_PASSWORD", "L+cUG4J5U7w%dE!")

# ===================== TELEGRAM CONFIG =====================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7593061997:AAFHBX_JOnMH_vjAB6F9DRdJgVDmORXiX7g")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "6452489265")
TELEGRAM_POLL_TIMEOUT = int(os.getenv("TELEGRAM_POLL_TIMEOUT", 20))

# ===================== IVASMS URLS =====================
LOGIN_URL = "https://www.ivasms.com/login"
LIVE_SMS_URL = "https://www.ivasms.com/portal/live/my_sms"
WS_BASE = "wss://ivasms.com:2087/socket.io/"

# API Endpoints
NUMBERS_BASE_URL = "https://www.ivasms.com/portal/numbers"
ADD_NUMBER_URL = "https://www.ivasms.com/portal/numbers/termination/number/add"
REMOVE_NUMBER_URL = "https://www.ivasms.com/portal/numbers/return/number/bluck"

# ===================== APP SETTINGS =====================
NUMBERS_PAGE_SIZE = 50

# Headers to mimic a real browser request (prevents 403 Forbidden on API calls)
NUMBERS_HEADERS = {
    "Host": "www.ivasms.com",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.ivasms.com/portal/numbers",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}
