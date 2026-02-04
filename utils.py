import sys
import time
import re
from datetime import datetime

# ===================== LOGGING =====================

# ANSI Colors for Terminal Output (Railway logs support this)
class Colors:
    PURPLE = "\033[38;5;141m"
    GREEN = "\033[92m"
    CYAN = "\033[96m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"

def log(msg: str, level: str = "INFO") -> None:
    """
    Structured logging with timestamps and icons.
    """
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

    # Flush output immediately for Docker/Railway
    print(f"{Colors.CYAN}[{ts}]{Colors.RESET} {icon} [{color}{level}{Colors.RESET}] {msg}", flush=True)

# ===================== FORMATTING =====================

def human_time(ts: float | None = None) -> str:
    """Convert timestamp to readable string."""
    if ts is None:
        ts = time.time()
    return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")

def strip_html(text: str) -> str:
    """Remove HTML tags from strings."""
    return re.sub('<[^<]+?>', '', text)

def extract_otp(message_text: str) -> str | None:
    """
    Regex to find OTP codes in messages.
    Matches 4-8 digits, optionally with a dash.
    """
    if not message_text:
        return None
    
    # Pattern: Look for isolated sequence of digits
    match = re.search(r"\b(\d{3,8}(?:-\d{3,8})?)\b", message_text)
    return match.group(1) if match else None
