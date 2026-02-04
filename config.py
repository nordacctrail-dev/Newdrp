import os

# ===================== TELEGRAM SETTINGS =====================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "YOUR_CHAT_ID_HERE")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# ===================== IVASMS CREDENTIALS =====================
IVASMS_EMAIL = os.getenv("IVASMS_EMAIL", "your_email@example.com")
IVASMS_PASSWORD = os.getenv("IVASMS_PASSWORD", "your_password")

# ===================== DATABASE SETTINGS =====================
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = "ivasms_bot"

# ===================== ENDPOINTS =====================
BASE_URL = "https://ivasms.com"
LOGIN_URL = f"{BASE_URL}/login"
LIVE_SMS_URL = f"{BASE_URL}/livesms"

# API Endpoints
NUMBERS_BASE_URL = f"{BASE_URL}/numbers"
ADD_NUMBER_URL = f"{BASE_URL}/add_number"
REMOVE_NUMBER_URL = f"{BASE_URL}/remove_number"
