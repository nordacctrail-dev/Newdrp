import os

# ===================== RAILWAY / DOCKER CONFIG =====================
# Path to Chrome. On Railway/Linux, usually /usr/bin/google-chrome
CHROMIUM_BINARY = os.getenv("CHROMIUM_BINARY", "/usr/bin/google-chrome")

# ===================== TELEGRAM CONFIG =====================
# Get these from @BotFather and @userinfobot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TOKEN_HERE")
# Your numeric User ID (This user is the Super Admin/Owner)
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# ===================== IVASMS URLS =====================
IVASMS_BASE_URL = "https://www.ivasms.com"
IVASMS_LOGIN_URL = "https://www.ivasms.com/login"
LIVE_SMS_URL = "https://www.ivasms.com/portal/live/my_sms"

# API Endpoints
NUMBERS_BASE_URL = "https://www.ivasms.com/portal/numbers"
ADD_NUMBER_URL = "https://www.ivasms.com/portal/numbers/termination/number/add"
REMOVE_NUMBER_URL = "https://www.ivasms.com/portal/numbers/return/number/bluck"

# ===================== APP SETTINGS =====================
DB_NAME = "ivasms_bot.db"
