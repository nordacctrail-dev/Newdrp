# config.py
import os

# --- CREDENTIALS ---
# Replace with your actual details
EMAIL = "siamkushtia33@gmail.com"
PASSWORD = "L+cUG4J5U7w%dE!"

# --- TELEGRAM ---
BOT_TOKEN = "7593061997:AAFHBX_JOnMH_vjAB6F9DRdJgVDmORXiX7g"
ADMIN_CHAT_ID = "6452489265"

# --- URLS ---
LOGIN_URL = "https://www.ivasms.com/login"
LIVE_SMS_URL = "https://www.ivasms.com/portal/live/my_sms"
NUMBERS_URL = "https://www.ivasms.com/portal/numbers"
DASHBOARD_URL = "https://www.ivasms.com/portal"

# --- SYSTEM ---
HEADLESS = True  # Set to False for debugging
USER_DATA_DIR = "ivasms_profile"  # For persistent sessions
COOKIE_FILE = "ivasms_cookies.json"

# --- TIMEOUTS ---
POLL_INTERVAL = 5  # Seconds between checks
CLOUDFLARE_WAIT = 6
