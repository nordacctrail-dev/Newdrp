import os

# ===================== RAILWAY / DOCKER CONFIG =====================
CHROMIUM_BINARY = os.getenv("CHROMIUM_BINARY", "/usr/bin/google-chrome")

# ===================== DATABASE CONFIG (NEW) =====================
# Update this with your actual MongoDB Connection String
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = "ivasms_bot"

# ===================== TELEGRAM CONFIG =====================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# ===================== IVASMS URLS =====================
IVASMS_BASE_URL = "https://www.ivasms.com"
IVASMS_LOGIN_URL = "https://www.ivasms.com/login"
LIVE_SMS_URL = "https://www.ivasms.com/portal/live/my_sms"

# API Endpoints
NUMBERS_BASE_URL = "https://www.ivasms.com/portal/numbers"
ADD_NUMBER_URL = "https://www.ivasms.com/portal/numbers/termination/number/add"
REMOVE_NUMBER_URL = "https://www.ivasms.com/portal/numbers/return/number/bluck"
