import asyncio

# ===================== RUNTIME MEMORY =====================

# Controls the main loop lifecycle
shutdown_event = asyncio.Event()

# Selenium Driver Reference (accessed by multiple threads/tasks)
driver_ref = None

# ===================== DATA STORE =====================

# Cookies & Tokens (Stored in RAM only)
# Format: {'name': 'value', ...}
current_cookies = {}

# CSRF Token (Extracted from HTML)
current_csrf_token = None

# User Info (Extracted for WebSocket auth)
current_livesms_user = None
current_livesms_token = None

# ===================== METRICS & HISTORY =====================

# OTP Storage
# Stores last 50 OTPs for the /history command
MAX_HISTORY_SIZE = 50
otp_history = []  

# Statistics Counter
otp_stats = {
    "total": 0,
    "by_originator": {},
    "by_country": {},
}

# Numbers Cache
# Format: { 'RANGE_NAME': ['id1', 'id2'], ... }
numbers_ids_by_group = {} 
numbers_last_update = 0.0

# ===================== ALERTS & STATUS =====================

# Status of various monitoring subsystems
# Values: "ACTIVE", "RESOLVED", "FAILED", or None
alert_state = {
    "cloudflare": None,
    "session": None,
}

# Track if we have already run the Cloudflare auto-solver to prevent loops
cf_solver_ran = False
