import sys
import time
import re
import os
import json
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, List, Dict, Tuple

# =========================================================================
#                                STATE
# =========================================================================

# Controls the main loop lifecycle
shutdown_event = asyncio.Event()

# Selenium Driver Reference (accessed by multiple threads/tasks)
driver_ref = None

# SIGNAL: Tells the browser thread to go solve Cloudflare ASAP
force_refresh_cookies = False  

# --- DATA STORE ---

# Cookies & Tokens (Stored in RAM only)
current_cookies = {}

# CSRF Token (Extracted from HTML)
current_csrf_token = None

# User Info (Extracted for WebSocket auth)
current_livesms_user = None
current_livesms_token = None

# --- METRICS & HISTORY ---

# OTP Storage (Last 50 OTPs)
MAX_HISTORY_SIZE = 50
otp_history = []  

# Statistics Counter
otp_stats = {
    "total": 0,
    "by_originator": {},
    "by_country": {},
}

# Numbers Cache [ cite: e.zip/state.py ]
# Format: { 'RANGE_NAME': [{'number': '...', 'id': '...'}], ... }
numbers_data = {}  
numbers_last_update = 0.0

# --- ALERTS & STATUS ---

# Status of various monitoring subsystems
alert_state = {
    "cloudflare": None,
    "session": None,
}

# Trackers
add_number_pending = {} # Tracks user states for adding numbers
temp_remove_list = []   # For bulk delete confirmation

# =========================================================================
#                                UTILITIES
# =========================================================================

class Colors:
    PURPLE = "\033[38;5;141m"
    GREEN = "\033[92m"
    CYAN = "\033[96m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"

def log(msg: str, level: str = "INFO") -> None:
    """Structured logging with timestamps and icons."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if level == "OK":
        icon = "✅"
        color = Colors.GREEN
    elif level == "WARN":
        icon = "⚠️"
        color = Colors.YELLOW
    elif level == "ERROR":
        icon = "❌"
        color = Colors.RED
    else:
        icon = "ℹ️"
        color = Colors.CYAN

    print(f"{Colors.CYAN}[{ts}]{Colors.RESET} {icon} [{color}{level}{Colors.RESET}] {msg}", flush=True)

# --- FORMATTING ---

def human_time(ts: float | None = None) -> str:
    """Convert timestamp to readable string."""
    if ts is None:
        ts = time.time()
    return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")

def get_bst_time() -> str:
    bst = timezone(timedelta(hours=6))
    return datetime.now(bst).strftime("%b %d, %I:%M %p")

def format_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"

def strip_html(text: str) -> str:
    """Remove HTML tags from strings."""
    return re.sub('<[^<]+?>', '', text)

def extract_otp(message_text: str) -> str | None:
    """Regex to find OTP codes (4-8 digits)."""
    if not message_text:
        return None
    match = re.search(r"\b(\d{3,8}(?:-\d{3,8})?)\b", message_text)
    return match.group(1) if match else None

def fmt_num(num: Any) -> str:
    if num is None: return "Unknown"
    if isinstance(num, list):
        num = num[0] if len(num) > 0 else "Unknown"
    s = str(num).strip()
    if s in ["Unknown", "N/A", "", "None"]: return "Unknown"
    clean = s.lstrip('+')
    return f"+{clean}"

def mask_did(num: str) -> str:
    s = str(num).strip()
    if len(s) < 8 or "Unknown" in s: return s
    return f"{s[:4]}****{s[-3:]}"

# --- MANAGERS ---

class CountryManager:
    """Handles Country Code detection and Flags."""
    PREFIX_DATA = {
        '1': ('USA/Canada', '🇺🇸'), '7': ('Russia', '🇷🇺'),
        '20': ('Egypt', '🇪🇬'), '27': ('South Africa', '🇿🇦'), '30': ('Greece', '🇬🇷'), '31': ('Netherlands', '🇳🇱'),
        '32': ('Belgium', '🇧🇪'), '33': ('France', '🇫🇷'), '34': ('Spain', '🇪🇸'), '36': ('Hungary', '🇭🇺'),
        '39': ('Italy', '🇮🇹'), '40': ('Romania', '🇷🇴'), '41': ('Switzerland', '🇨🇭'), '43': ('Austria', '🇦🇹'),
        '44': ('United Kingdom', '🇬🇧'), '45': ('Denmark', '🇩🇰'), '46': ('Sweden', '🇸🇪'), '47': ('Norway', '🇳🇴'),
        '48': ('Poland', '🇵🇱'), '49': ('Germany', '🇩🇪'), '51': ('Peru', '🇵🇪'), '52': ('Mexico', '🇲🇽'),
        '53': ('Cuba', '🇨🇺'), '54': ('Argentina', '🇦🇷'), '55': ('Brazil', '🇧🇷'), '56': ('Chile', '🇨🇱'),
        '57': ('Colombia', '🇨🇴'), '58': ('Venezuela', '🇻🇪'), '60': ('Malaysia', '🇲🇾'), '61': ('Australia', '🇦🇺'),
        '62': ('Indonesia', '🇮🇩'), '63': ('Philippines', '🇵🇭'), '64': ('New Zealand', '🇳🇿'), '65': ('Singapore', '🇸🇬'),
        '66': ('Thailand', '🇹🇭'), '81': ('Japan', '🇯🇵'), '82': ('South Korea', '🇰🇷'), '84': ('Vietnam', '🇻🇳'),
        '86': ('China', '🇨🇳'), '90': ('Turkey', '🇹🇷'), '91': ('India', '🇮🇳'), '92': ('Pakistan', '🇵🇰'),
        '93': ('Afghanistan', '🇦🇫'), '94': ('Sri Lanka', '🇱🇰'), '95': ('Myanmar', '🇲🇲'), '98': ('Iran', '🇮🇷'),
        '211': ('South Sudan', '🇸🇸'), '212': ('Morocco', '🇲🇦'), '213': ('Algeria', '🇩🇿'), '216': ('Tunisia', '🇹🇳'),
        '218': ('Libya', '🇱🇾'), '220': ('Gambia', '🇬🇲'), '221': ('Senegal', '🇸🇳'), '222': ('Mauritania', '🇲🇷'),
        '223': ('Mali', '🇲🇱'), '224': ('Guinea', '🇬🇳'), '225': ('Ivory Coast', '🇨🇮'), '226': ('Burkina Faso', '🇧🇫'),
        '227': ('Niger', '🇳🇪'), '228': ('Togo', '🇹🇬'), '229': ('Benin', '🇧🇯'), '230': ('Mauritius', '🇲🇺'),
        '231': ('Liberia', '🇱🇷'), '232': ('Sierra Leone', '🇸🇱'), '233': ('Ghana', '🇬🇭'), '234': ('Nigeria', '🇳🇬'),
        '235': ('Chad', '🇹🇩'), '236': ('Central African Republic', '🇨🇫'), '237': ('Cameroon', '🇨🇲'),
        '238': ('Cape Verde', '🇨🇻'), '239': ('Sao Tome', '🇸🇹'), '240': ('Equatorial Guinea', '🇬.🇶'),
        '241': ('Gabon', '🇬🇦'), '242': ('Congo', '🇨🇬'), '243': ('DR Congo', '🇨🇩'), '244': ('Angola', '🇦🇴'),
        '245': ('Guinea-Bissau', '🇬🇼'), '248': ('Seychelles', '🇸🇨'), '249': ('Sudan', '🇸🇩'), '250': ('Rwanda', '🇷🇼'),
        '251': ('Ethiopia', '🇪🇹'), '252': ('Somalia', '🇸🇴'), '253': ('Djibouti', '🇩🇯'), '254': ('Kenya', '🇰🇪'),
        '255': ('Tanzania', '🇹🇿'), '256': ('Uganda', '🇺🇬'), '257': ('Burundi', '🇧🇮'), '258': ('Mozambique', '🇲🇿'),
        '260': ('Zambia', '🇿🇲'), '261': ('Madagascar', '🇲🇬'), '262': ('Reunion', '🇷🇪'), '263': ('Zimbabwe', '🇿🇼'),
        '264': ('Namibia', '🇳🇦'), '265': ('Malawi', '🇲🇼'), '266': ('Lesotho', '🇱🇸'), '267': ('Botswana', '🇧🇼'),
        '268': ('Eswatini', '🇸🇿'), '269': ('Comoros', '🇰🇲'), '290': ('Saint Helena', '🇸🇭'), '291': ('Eritrea', '🇪🇷'),
        '297': ('Aruba', '🇦🇼'), '298': ('Faroe Islands', '🇫🇴'), '299': ('Greenland', '🇬🇱'), '350': ('Gibraltar', '🇬🇮'),
        '351': ('Portugal', '🇵🇹'), '352': ('Luxembourg', '🇱🇺'), '353': ('Ireland', '🇮🇪'), '354': ('Iceland', '🇮🇸'),
        '355': ('Albania', '🇦🇱'), '356': ('Malta', '🇲🇹'), '357': ('Cyprus', '🇨🇾'), '358': ('Finland', '🇫🇮'),
        '359': ('Bulgaria', '🇧🇬'), '370': ('Lithuania', '🇱🇹'), '371': ('Latvia', '🇱🇻'), '372': ('Estonia', '🇪🇪'),
        '373': ('Moldova', '🇲🇩'), '374': ('Armenia', '🇦🇲'), '375': ('Belarus', '🇧🇾'), '376': ('Andorra', '🇦🇩'),
        '377': ('Monaco', '🇲🇨'), '378': ('San Marino', '🇸🇲'), '380': ('Ukraine', '🇺🇦'), '381': ('Serbia', '🇷🇸'),
        '382': ('Montenegro', '🇲🇪'), '383': ('Kosovo', '🇽🇰'), '385': ('Croatia', '🇭🇷'), '386': ('Slovenia', '🇸🇮'),
        '387': ('Bosnia', '🇧🇦'), '389': ('North Macedonia', '🇲🇰'), '420': ('Czechia', '🇨🇿'),
        '421': ('Slovakia', '🇸🇰'), '423': ('Liechtenstein', '🇱🇮'), '500': ('Falkland Islands', '🇫🇰'),
        '501': ('Belize', '🇧🇿'), '502': ('Guatemala', '🇬🇹'), '503': ('El Salvador', '🇸🇻'), '504': ('Honduras', '🇭🇳'),
        '505': ('Nicaragua', '🇳🇮'), '506': ('Costa Rica', '🇨🇷'), '507': ('Panama', '🇵🇦'), '508': ('St. Pierre', '🇵🇲'),
        '509': ('Haiti', '🇭🇹'), '590': ('Guadeloupe', '🇬🇵'), '591': ('Bolivia', '🇧🇴'), '592': ('Guyana', '🇬🇾'),
        '593': ('Ecuador', '🇪🇨'), '594': ('French Guiana', '🇬🇫'), '595': ('Paraguay', '🇵🇾'), '596': ('Martinique', '🇲🇶'),
        '597': ('Suriname', '🇸🇷'), '598': ('Uruguay', '🇺🇾'), '670': ('Timor-Leste', '🇹🇱'), '672': ('Norfolk Island', '🇳🇫'),
        '673': ('Brunei', '🇧🇳'), '674': ('Nauru', '🇳🇷'), '675': ('Papua New Guinea', '🇵🇬'), '676': ('Tonga', '🇹🇴'),
        '677': ('Solomon Islands', '🇸🇧'), '678': ('Vanuatu', '🇻🇺'), '679': ('Fiji', '🇫🇯'), '680': ('Palau', '🇵🇼'),
        '681': ('Wallis & Futuna', '🇼🇫'), '682': ('Cook Islands', '🇨🇰'), '683': ('Niue', '🇳🇺'), '685': ('Samoa', '🇼🇸'),
        '686': ('Kiribati', '🇰🇮'), '687': ('New Caledonia', '🇳🇨'), '688': ('Tuvalu', '🇹🇻'), '689': ('French Polynesia', '🇵🇫'),
        '690': ('Tokelau', '🇹🇰'), '691': ('Micronesia', '🇫🇲'), '692': ('Marshall Islands', '🇲🇭'), '850': ('North Korea', '🇰🇵'),
        '852': ('Hong Kong', '🇭🇰'), '853': ('Macau', '🇲🇴'), '855': ('Cambodia', '🇰🇭'), '856': ('Laos', '🇱🇦'),
        '880': ('Bangladesh', '🇧🇩'), '886': ('Taiwan', '🇹🇼'), '960': ('Maldives', '🇲🇻'), '961': ('Lebanon', '🇱🇧'),
        '962': ('Jordan', '🇯🇴'), '963': ('Syria', '🇸🇾'), '964': ('Iraq', '🇮🇶'), '965': ('Kuwait', '🇰🇼'),
        '966': ('Saudi Arabia', '🇸🇦'), '967': ('Yemen', '🇾🇪'), '968': ('Oman', '🇴🇲'), '970': ('Palestine', '🇵🇸'),
        '971': ('UAE', '🇦🇪'), '972': ('Israel', '🇮🇱'), '973': ('Bahrain', '🇧🇭'), '974': ('Qatar', '🇶🇦'),
        '975': ('Bhutan', '🇧🇹'), '976': ('Mongolia', '🇲🇳'), '977': ('Nepal', '🇳🇵'), '992': ('Tajikistan', '🇹🇯'),
        '993': ('Turkmenistan', '🇹🇲'), '994': ('Azerbaijan', '🇦🇿'), '995': ('Georgia', '🇬🇪'), '996': ('Kyrgyzstan', '🇰🇬'),
        '998': ('Uzbekistan', '🇺🇿')
    }

    @staticmethod
    def get_country_info(number: str) -> Tuple[str, str]:
        """
        Determines country name AND flag from phone number string.
        Returns: (Country Name, Flag Emoji)
        """
        clean_num = ''.join(filter(str.isdigit, str(number)))
        # Check from 3 digits down to 1
        for length in range(3, 0, -1):
            prefix = clean_num[:length]
            if prefix in CountryManager.PREFIX_DATA:
                return CountryManager.PREFIX_DATA[prefix]
        return "Other", "🏳️"

    @staticmethod
    def get_flag_by_name(country_name: str) -> str:
        """Reverse lookup for flag by name (used for menus)"""
        for name, flag in CountryManager.PREFIX_DATA.values():
            if name == country_name:
                return flag
        return "🏳️"

class ExportManager:
    @staticmethod
    def generate(numbers: List[Any], base_name: str) -> str:
        """Generates a clean .txt file."""
        export_dir = os.path.abspath("exports")
        os.makedirs(export_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_name = "".join(x for x in base_name if x.isalnum() or x in "_-") or "Export"
        filename = os.path.join(export_dir, f"{clean_name}_{timestamp}.txt")
        
        try:
            valid_numbers = [str(n).strip() for n in numbers if n]
            content = "\n".join(valid_numbers) if valid_numbers else "No numbers found."
            
            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)
            return filename
        except Exception as e:
            logging.error(f"Error writing file {filename}: {e}")
            raise e
