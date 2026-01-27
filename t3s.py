#!/usr/bin/env python3
"""
IVASMS All-in-One:

- Selenium GUI login watcher (Chromium in XFCE)
  • Detects Cloudflare
  • Tries to auto-click Cloudflare checkbox (SeleniumBase GUI click)
  • Saves cookies automatically to ivasms_cookies.json / .pkl (backup only)
  • Tracks session changes (login/logout/account switch) and updates cookies
  • Silently captures CSRF token from HTML and stores it ONLY in memory variable

- OTP Receiver via WebSocket (/livesms)
  • Fetches livesms token + user from /portal/live/my_sms using BROWSER (Selenium)
  • Connects to wss://ivasms.com:2087/socket.io/?token=...&user=...&EIO=4&transport=websocket
  • Parses OTP SMS and sends to Telegram with stats/history

- Numbers Fetch (ON DEMAND ONLY)
  • NO continuous monitor loop.
  • When you press:
        📋 Numbers  or  🔎 Choose Range
    in Telegram:
        → fetches /portal/numbers once using current BROWSER cookies
        → groups by range
        → paginates in Telegram UI
        → also caches NumberID[] per range for removal

- Add Number (ON DEMAND)
  • Telegram UI:
        1) Press “➕ Add Number” button
        2) Bot asks for termination ID
        3) You send the ID (e.g. 980693)
        4) Script calls /portal/numbers/termination/number/add
  • Uses current BROWSER cookies + CSRF token (from page HTML, kept in memory)

- Remove Numbers (ON DEMAND, BY RANGE)
  • Telegram UI:
        1) Press “🗑 Remove Numbers”
        2) Bot shows ranges (same style as Choose Range)
        3) Select a range, confirm removal
        4) Script POSTs NumberID[] for that range to /portal/numbers/return/number/bluck
"""

from __future__ import annotations
import os
import sys
import re
import json
import time
import pickle
import threading
import traceback
from datetime import datetime
from urllib.parse import quote_plus

import requests
import websocket
import html
from seleniumbase import Driver
from seleniumbase import SB
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException

# ===================== CONFIGURATION =====================

LOGIN_URL = "https://www.ivasms.com/login"
LIVE_SMS_URL = "https://www.ivasms.com/portal/live/my_sms"

COOKIE_JSON = "ivasms_cookies.json"
COOKIE_PKL = "ivasms_cookies.pkl"

CHROMIUM_BINARY = "/data/data/com.termux/files/usr/bin/chromium-browser"

# Shared cookies dict (fallback if file not present)
cookies = {
    # normally empty; Selenium writes ivasms_cookies.json
}

HTTP_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
}

TELEGRAM_BOT_TOKEN = "7593061997:AAFHBX_JOnMH_vjAB6F9DRdJgVDmORXiX7g"
TELEGRAM_ADMIN_CHAT_ID = "8506144731"

WS_BASE   = "wss://ivasms.com:2087/socket.io/"
HTTP_URL  = "https://www.ivasms.com/portal/live/my_sms"

NUMBERS_BASE_URL = "https://www.ivasms.com/portal/numbers"
NUMBERS_PAGE_SIZE = 50  # you set this to 50 in panel

NUMBERS_HEADERS = {
    "Host": "www.ivasms.com",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.ivasms.com/portal/numbers",
    "User-Agent": HTTP_HEADERS["User-Agent"],
}

TELEGRAM_POLL_TIMEOUT = 20
NUMBERS_CONNECT_TIMEOUT = 10.0
NUMBERS_READ_TIMEOUT = 15.0  # longer to avoid ReadTimeout while adding/removing
DRIVER = None  # global pointer so WS error handler can touch the browser
# Global: allow Cloudflare auto-solver to run only once per script run
CF_SOLVER_RAN = False
PAGE_SIZE = 35  # pagination size for Telegram numbers text

COOKIE_FILE = COOKIE_JSON

# ===================== RUNTIME STATE (COOKIES + CSRF IN MEMORY) =====================

# Always use these for live HTTP/WS:
current_cookies: dict = {}       # filled from Selenium driver snapshots
current_csrf_token: str = ""     # extracted from HTML, not from cookies/file

# ===================== UI / TERMINAL STYLE =====================

EMOJI_FIRE = "🔥"
EMOJI_WHATSAPP = "💬"
EMOJI_TELEGRAM = "📨"
EMOJI_PHONE = "📞"
EMOJI_ID = "🆔"
EMOJI_GLOBE = "🌎"
EMOJI_SAMPLE = "✉️"
EMOJI_OK = "✅"
EMOJI_WARN = "⚠️"
EMOJI_ERROR = "❌"

PURPLE = "\033[38;5;141m"
GREEN = "\033[92m"
CYAN = "\033[96m"
RESET = "\033[0m"
WIDTH = 80
TOP = f"{PURPLE}╭{'─' * (WIDTH - 2)}╮{RESET}"
MID = f"{PURPLE}├{'─' * (WIDTH - 2)}┤{RESET}"
BOT = f"{PURPLE}╰{'─' * (WIDTH - 2)}╯{RESET}"

_state = {
    "connected": False,
    "last_http_ok": None,
}

# OTP stats/history
otp_stats = {
    "total": 0,
    "by_originator": {},
    "by_country": {},
}
otp_history = []
MAX_HISTORY = 50

# Numbers state (updated only when user asks)
numbers_groups = {}          # {range_name: {number,...}}
numbers_ids_by_group = {}    # {range_name: [number_id,...]}
numbers_last_update = 0.0
numbers_total_numbers = 0
numbers_error = None

start_time = time.time()
_LAST_UPDATE_ID = None  # Telegram

# Alert messages (Cloudflare / session / numbers)
_alert_state = {
    "cloudflare": None,  # {"chat_id":..., "message_id":..., "status":...}
    "session": None,
    "numbers": None,
}

# Add-number pending state (per chat)
addnum_pending = set()       # set of chat_id strings waiting for an ID

# Remove-range pending state
rmrange_select_pending = set()      # waiting for user to choose range
rmrange_confirm_for_chat = {}       # chat_id -> range_name pending confirm

# ===================== HELPERS =====================

def human_time(ts: float | None = None) -> str:
    if ts is None:
        ts = time.time()
    return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")


def human_duration(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    h, r = divmod(seconds, 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def log(msg: str, level: str = "INFO") -> None:
    emoji = (
        EMOJI_OK if level == "OK"
        else EMOJI_WARN if level == "WARN"
        else EMOJI_ERROR if level == "ERROR"
        else "ℹ️"
    )
    print(f"{CYAN}[{human_time()}]{RESET} {emoji} [{level}] {msg}", flush=True)


def strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def plusify(n: str) -> str:
    return n if n.startswith("+") else f"+{n}"


def chunk_lines(lines, page: int, page_size: int):
    import math
    total_pages = max(1, math.ceil(len(lines) / page_size))
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    return lines[start:end], total_pages

# ===================== COOKIE UTILITIES (Selenium side) =====================

# put this near top with other globals
_snapshot_log_done = False

def snapshot_cookies(driver, *, log_once: bool = False):
    """
    Extract cookies from Selenium driver → (cookies_list, simple_dict)
    and update current_cookies.

    If log_once=True → only logs first time per script run.
    """
    global current_cookies, _snapshot_log_done

    try:
        cookies_all = driver.get_cookies()
    except Exception as e:
        log(f"snapshot_cookies: driver.get_cookies() failed: {e}", "WARN")
        return [], {}

    simple = {}
    for c in cookies_all:
        name   = c.get("name")
        value  = c.get("value")
        domain = (c.get("domain") or "").lower()

        if not name or value is None:
            continue
        if "ivasms.com" not in domain:
            continue

        simple[name] = value

    current_cookies = dict(simple)

    if log_once and not _snapshot_log_done:
        log(f"snapshot_cookies: {len(simple)} cookies captured", "OK")
        _snapshot_log_done = True

    return cookies_all, simple


def fingerprint(simple: dict) -> str:
    """Create a unique signature for current cookies dict."""
    return json.dumps(sorted(simple.items()), separators=(",", ":"))


def save_cookie_files(cookies_all, simple):
    """Write cookies to PKL and JSON."""
    try:
        with open(COOKIE_PKL, "wb") as f:
            pickle.dump(cookies_all, f)
        with open(COOKIE_JSON, "w", encoding="utf-8") as f:
            json.dump(simple, f, ensure_ascii=False, indent=2)
        print(f"✅ Saved {len(simple)} cookies → {COOKIE_JSON} + {COOKIE_PKL}")
    except Exception as e:
        print(f"⚠️ save_cookie_files error: {e}")


def persist_live_cookies(driver, reason: str = ""):
    """
    Snapshot real browser cookies and save to disk.
    Called:
        - after successful login
        - when cookie monitor detects update
    """
    try:
        cookies_all, simple = snapshot_cookies(driver)

        if not simple:
            log(f"persist_live_cookies: NOT saving, empty cookie set (reason={reason})", "WARN")
            return

        save_cookie_files(cookies_all, simple)
        log(f"persist_live_cookies: wrote {len(simple)} cookies (reason={reason})", "OK")

    except Exception as e:
        log(f"persist_live_cookies error ({reason}): {e}", "WARN")

# ===================== CSRF TOKEN EXTRACTOR (from HTML) =====================

def extract_csrf_token_from_html(html_text: str | None) -> str | None:
    """
    Extracts the CSRF token from the HTML:
      - <meta name="csrf-..." content="TOKEN">
      - or <input type="hidden" name="_token" value="TOKEN">
    Returns TOKEN or None. (NO printing of the token.)
    """
    if not html_text:
        return None

    m = re.search(r'<meta\s+name="csrf-[^"]*"\s+content="([^"]+)"', html_text)
    if m:
        return m.group(1)

    m = re.search(r'name="_token"\s+value="([^"]+)"', html_text)
    if m:
        return m.group(1)

    return None


def maybe_update_csrf_from_html(html_text: str | None):
    """Update in-memory CSRF token if found; silent (no file)."""
    global current_csrf_token
    csrf = extract_csrf_token_from_html(html_text)
    if not csrf:
        return
    if csrf != current_csrf_token:
        current_csrf_token = csrf
        log("Updated in-memory CSRF token from HTML.", "OK")

# ===================== CLOUDFLARE DETECTION =====================

def looks_like_cloudflare(html_text: str) -> bool:
    """Heuristic to detect Cloudflare challenge page."""
    t = html_text.lower()
    if "cloudflare" in t and ("just a moment" in t or "checking your browser" in t):
        return True
    if "cf-challenge" in t or "cf-browser-verification" in t:
        return True
    if "attention required" in t and "one more step" in t:
        return True
    if "verify you are human" in t:
        return True
    if "challenge-platform" in t and "managed" in t:
        return True
    return False

# ===================== TELEGRAM ALERT UTIL =====================

def telegram_api_call(method: str, payload: dict, timeout=10):
    token = TELEGRAM_BOT_TOKEN.strip()
    if not token:
        raise RuntimeError("Telegram token not configured.")
    url = f"https://api.telegram.org/bot{token}/{method}"
    r = requests.post(url, json=payload, timeout=timeout)
    try:
        return r.json()
    except Exception:
        return {"ok": False, "status_code": r.status_code, "text": r.text}


def send_telegram_raw(chat_id: str, text: str, parse_mode: str | None = None,
                       reply_markup: dict | None = None):
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
        payload["disable_web_page_preview"] = True
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return telegram_api_call("sendMessage", payload)


def send_or_edit_alert(kind: str, status: str, text: str):
    """
    kind: "cloudflare", "session", "numbers"
    status: "ACTIVE" | "RESOLVED" | "FAILED"
    """
    chat_id = str(TELEGRAM_ADMIN_CHAT_ID).strip()
    if not chat_id:
        return

    prefix = {
        "cloudflare": "☁️ Cloudflare",
        "session": "🔑 Session",
        "numbers": "📋 Numbers",
    }.get(kind, "⚠️ Alert")

    label = status.upper()
    full_text = f"{prefix} [{label}]\n\n{text}"

    prev = _alert_state.get(kind)

    if prev and prev.get("chat_id") == chat_id:
        try:
            telegram_api_call(
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": prev["message_id"],
                    "text": full_text,
                },
            )
            prev["status"] = status
            return
        except Exception:
            pass

    try:
        res = send_telegram_raw(chat_id, full_text)
        if res.get("ok"):
            _alert_state[kind] = {
                "chat_id": chat_id,
                "message_id": res["result"]["message_id"],
                "status": status,
            }
    except Exception:
        pass

# ===================== DISPLAY / DRIVER SETUP =====================

def check_display():
    if "DISPLAY" not in os.environ:
        print("❌ Error: DISPLAY not set. Run inside XFCE4 / Termux-X11.")
        sys.exit(1)
    print(f"✅ Detected GUI Display: {os.environ['DISPLAY']}")


def setup_driver():
    print("🚀 Starting Chromium in GUI mode...")
    try:
        driver = Driver(
            browser="chrome",
            uc=True,
            headless=False,
            binary_location=CHROMIUM_BINARY,
            no_sandbox=True,
            disable_gpu=True,
        )
        print("✅ Loaded Anti-Detect Driver.")
    except Exception:
        print("⚠️ UC Mode failed. Falling back to standard mode...")
        driver = Driver(
            browser="chrome",
            uc=False,
            headless=False,
            binary_location=CHROMIUM_BINARY,
            no_sandbox=True,
            disable_gpu=True,
        )
    return driver

# ===================== CLOUDFLARE SOLVER  =====================



# ===================== SELENIUM LOGIN FLOW =====================


# ===================== COOKIE / CLOUDFLARE MONITOR =====================

def cookies_monitor_loop(driver):
    """
    After successful login, continuously:
    - Detect Cloudflare -> ALERT -> AUTO-SOLVE (once)
    - Detect cookie changes (session updated)
    - Save updated cookies to COOKIE_JSON / PKL (backup)
    - Detect auto-logout (login page)
    Stops ONLY if the real browser window is actually closed.
    """
    print("\n--- 🕵️ Cookie & Cloudflare Monitor ACTIVE (with Auto-Solver) ---")

    try:
        cookies_init, simple_init = snapshot_cookies(driver)
        fp_prev = fingerprint(simple_init)
        last_len = len(driver.page_source)
        session_prev_logged_in = "login" not in driver.current_url.lower()
    except Exception as e:
        log(f"Cookie monitor init failed: {e}", "WARN")
        return

    cf_prev = False

    while True:
        time.sleep(5)
        try:
            page_source = driver.page_source
            curr_len = len(page_source)
            curr_url = driver.current_url.lower()

            # -------- CLOUDFLARE CHECK --------
            cf_now = looks_like_cloudflare(page_source)

            if cf_now and not cf_prev:
                msg = (
                    "Cloudflare detected on active session.\n"
                    "Waiting 6 seconds, then trying _ auto-solve once..."
                )
                print(f"⚠️ {msg}")
                send_or_edit_alert("cloudflare", "ACTIVE", msg)

                time.sleep(6)
                attempted = attempt_cloudflare_auto_solve(driver)
                time.sleep(2)

                page_source_after = driver.page_source
                still_cf = looks_like_cloudflare(page_source_after)

                if not still_cf:
                    print(f"{EMOJI_OK} Cloudflare challenge cleared (monitor phase).")
                    send_or_edit_alert(
                        "cloudflare",
                        "RESOLVED",
                        "Cloudflare cleared automatically (monitor)."
                    )
                else:
                    if attempted:
                        print("⚠️ Cloudflare still present after auto-solve. Please solve manually.")
                    else:
                        print("⚠️ Auto-solve not possible. Please solve manually.")
                    send_or_edit_alert(
                        "cloudflare",
                        "FAILED",
                        "Auto-solve failed. Please manually tap the checkbox."
                    )

            elif not cf_now and cf_prev:
                print(f"{EMOJI_OK} Cloudflare challenge cleared (monitor phase).")
                send_or_edit_alert(
                    "cloudflare",
                    "RESOLVED",
                    "Cloudflare cleared (monitor)."
                )

            cf_prev = cf_now

            # -------- COOKIE CHANGES --------
            if not cf_now:
                cookies_now, simple_now = snapshot_cookies(driver)
                fp_now = fingerprint(simple_now)
                if fp_now != fp_prev:
                    print("📝 Cookies changed (session updated). Saving backup...")
                    maybe_update_csrf_from_html(page_source)
                    persist_live_cookies(driver, reason="cookie monitor change")
                    fp_prev = fp_now

            # -------- SESSION CHECK --------
            is_login_page = "login" in curr_url
            session_now_logged_in = not is_login_page

            if session_prev_logged_in and not session_now_logged_in:
                print("⚠️ Session lost. Please log in again manually.")
                send_or_edit_alert(
                    "session",
                    "ACTIVE",
                    "Detected redirect to login page (session lost)."
                )

            if (not session_prev_logged_in) and session_now_logged_in:
                print("✅ Session restored after login.")
                send_or_edit_alert(
                    "session",
                    "RESOLVED",
                    "Login detected again, session restored."
                )

            session_prev_logged_in = session_now_logged_in

        # ============================
        #  FIXED WEBDRIVER EXCEPTIONS
        # ============================
        except WebDriverException as e:
            msg = str(e).lower()

            # Only stop on TRUE window-close errors
            if "no such window" in msg or "web view not found" in msg:
                log("Browser window appears closed; stopping cookie monitor loop.", "WARN")
                return

            # Everything else should NOT stop the loop
            log(f"Cookie monitor WebDriverException (ignored): {e}", "WARN")
            time.sleep(3)
            continue

        except Exception as e:
            print(f"⚠️ Cookie monitor loop error: {e}")
            time.sleep(3)

# ===================== COOKIE LOADER (backup only) =====================

def load_cookies_from_file(path: str = COOKIE_FILE) -> dict:
    if not os.path.exists(path):
        log(f"[cookies] {path} not found (backup missing).", "WARN")
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            log(f"[cookies] Loaded {len(data)} cookies from backup {path}", "OK")
            return data
        else:
            log(f"[cookies] {path} is not a dict, ignoring.", "WARN")
            return {}
    except Exception as e:
        log(f"[cookies] Failed to load {path}: {e}", "WARN")
        return {}

def get_live_cookies() -> dict:
    """
    Main source for all requests / WS:
      1) in-memory current_cookies (from browser)
      2) backup file
      3) static cookies dict
    """
    if current_cookies:
        return dict(current_cookies)
    backup = load_cookies_from_file()
    if backup:
        return backup
    return dict(cookies)
   
def build_ws_cookie_string(driver) -> str:
    """
    Always try to use LIVE browser cookies for WebSocket.
    Fallback to backup/json only if Selenium cookies fail.
    """
    try:
        # Prefer fresh cookies from the live browser
        _, simple = snapshot_cookies(driver)
        return "; ".join(f"{k}={v}" for k, v in simple.items() if v)
    except Exception as e:
        log(f"Failed to snapshot cookies from browser, using backup cookies: {e}", "WARN")
        # Fallback: in-memory / json / static
        active = get_live_cookies()
        return "; ".join(f"{k}={v}" for k, v in active.items() if v)

# ===================== PARSING HELPERS (WebSocket) =====================

def try_json(s):
    try:
        return json.loads(s) if isinstance(s, (str, bytes)) else None
    except Exception:
        return None


def find_json_array_in_text(text: str):
    if not isinstance(text, str):
        return None
    idx = text.find("[")
    if idx == -1:
        return None
    substr = text[idx:]
    parsed = try_json(substr)
    if isinstance(parsed, list):
        return parsed
    last = substr.rfind("]")
    if last != -1:
        cand = substr[: last + 1]
        parsed = try_json(cand)
        if isinstance(parsed, list):
            return parsed
    return None


def extract_otp_code_from_message(msg: str) -> str | None:
    if not msg:
        return None
    m = re.search(r"\b(\d{3,8}(?:-\d{3,8})?)\b", msg)
    return m.group(1) if m else None

# ===================== OTP RENDERING & NOTIFY =====================

def render_otp_panel(otp: dict) -> None:
    print("\n" + TOP)
    title_name = otp.get("originator") or "(unknown)"
    headline = f" {EMOJI_FIRE} OTP RECEIVED — {title_name}"
    pad = WIDTH - 4 - len(strip_ansi(headline))
    pad = max(pad, 0)
    print(f"{PURPLE}│{RESET}{GREEN}{headline}{' ' * pad}{PURPLE}│{RESET}")
    print(MID)

    def row(text):
        pad = WIDTH - 4 - len(strip_ansi(text))
        pad = max(pad, 0)
        print(f"{PURPLE}│{RESET} {text}{' ' * pad}{PURPLE}│{RESET}")

    row(f"{EMOJI_ID} Code: {otp.get('otp_code') or '-'}")
    row(f"{EMOJI_PHONE} To: {otp.get('recipient') or '-'}")
    row(f"{EMOJI_GLOBE} Country: {otp.get('country_iso') or '-'}")
    rng = otp.get("range") or "-"
    rev = otp.get("revenue") or "-"
    row(f"Range: {rng}")
    row(f"Revenue: {rev}")
    print(MID)
    msg = otp.get("message") or "-"
    msg_line = msg if len(msg) <= 64 else (msg[:61] + "…")
    row(f"{EMOJI_SAMPLE} Msg: {msg_line}")
    print(BOT + "\n")


def send_otp_notification(otp: dict) -> bool:
    token = TELEGRAM_BOT_TOKEN.strip()
    chat = str(TELEGRAM_ADMIN_CHAT_ID).strip()
    if not token or not chat:
        log("Telegram not configured — OTP not sent.", "WARN")
        return False
    try:
        originator = html.escape(str(otp.get("originator") or "-"))
        recipient  = html.escape(str(otp.get("recipient")  or "-"))
        country    = html.escape(str(otp.get("country_iso") or "-"))
        rng        = html.escape(str(otp.get("range") or "-"))
        revenue    = html.escape(str(otp.get("revenue") or "-"))
        code       = html.escape(str(otp.get("otp_code") or "-"))
        msg        = html.escape(str(otp.get("message") or "-"))
        ts         = html.escape(str(otp.get("time") or human_time()))

        msg_html = (
            "📩 <b>New OTP received</b>\n\n"
            f"📛 Originator: <code>{originator}</code>\n"
            f"📱 To: <code>{recipient}</code>\n"
            f"🌍 Country: <code>{country}</code>\n"
            f"📦 Range: <code>{rng}</code>\n"
            f"💰 Revenue: <code>{revenue}</code>\n"
            f"🔢 OTP Code: <b><code>{code}</code></b>\n\n"
            f"{EMOJI_SAMPLE} Message:\n<code>{msg}</code>\n\n"
            f"⏱ Time: {ts}"
        )
        res = send_telegram_raw(chat, msg_html, parse_mode="HTML")
        return bool(res.get("ok"))
    except Exception as e:
        log(f"Error sending OTP to Telegram: {e}", "ERROR")
        return False

# ===================== WEBSOCKET HANDLERS =====================

def on_open(ws) -> None:
    try:
        ws.send("40")
        ws.send("40/livesms,")
    except Exception:
        pass
    _state["connected"] = True
    log("WebSocket opened and /livesms handshake sent.", "OK")


def on_message(ws, raw_msg) -> None:
    try:
        text = raw_msg if isinstance(raw_msg, str) else raw_msg.decode(errors="ignore")
        process_frame_text(text)
    except Exception as exc:
        log(f"Exception in on_message: {exc}", "ERROR")
        traceback.print_exc()


def on_error(ws, err) -> None:
    """
    WebSocket error handler.

    - Always logs the error.
    - If it's a WebSocket handshake 403 (Cloudflare), we trigger the
      SAME 403 recovery helper that you use for HTTP (handle_http_403_during_ws),
      which:
        • opens LIVE_SMS_URL in browser
        • tries Cloudflare GUI auto-solve ONCE (respecting CF_SOLVER_RAN)
    - NO refresh for any other kind of WS error.
    """
    _state["connected"] = False
    err_str = str(err)
    log(f"WebSocket error: {err_str}", "ERROR")

    # Only act on handshake 403 (Cloudflare challenge)
    low = err_str.lower()
    if "handshake status 403" in low and ("cf-mitigated" in low or "cloudflare" in low):
        # If solver already ran once, don't spam refreshes.
        from time import time as _time
        global CF_SOLVER_RAN

        if CF_SOLVER_RAN:
            log("WS 403 looks like Cloudflare but solver already ran once; no more auto-refresh.", "WARN")
            return

        # We need the live Selenium driver to recover
        if DRIVER is None:
            log("WS 403 (Cloudflare) detected, but DRIVER is None (cannot refresh browser).", "WARN")
            return

        try:
            # Re-use your existing HTTP 403 recovery helper (it also does CF auto-solve).
            handle_http_403_during_ws(
                DRIVER,
                url="WebSocket handshake",
                reason=err_str,
            )
        except Exception as e:
            log(f"Error while handling WS 403 Cloudflare: {e}", "ERROR")
            traceback.print_exc()


def on_close(ws, code, reason) -> None:
    _state["connected"] = False
    log(f"WebSocket closed: code={code} reason={reason}", "WARN")


def process_frame_text(text: str):
    if "livesms" not in text:
        return

    arr = find_json_array_in_text(text)
    payload = None

    if isinstance(arr, list):
        if len(arr) == 1 and isinstance(arr[0], dict):
            payload = arr[0]
        elif len(arr) >= 2 and isinstance(arr[1], dict):
            payload = arr[1]
        elif len(arr) >= 1 and isinstance(arr[0], dict):
            payload = arr[0]

    if isinstance(payload, str):
        decoded = try_json(payload)
        if isinstance(decoded, dict):
            payload = decoded

    if not isinstance(payload, dict):
        return

    message_text = payload.get("message") or payload.get("text") or ""
    originator   = payload.get("originator") or payload.get("sender") or "(unknown)"
    recipient    = payload.get("recipient") or payload.get("to") or payload.get("number")
    country_iso  = (payload.get("country_iso") or "").upper()
    range_val    = payload.get("range") or payload.get("range_name")
    limit_flag   = payload.get("Limit") or payload.get("limit")
    revenue      = payload.get("client_revenue") or payload.get("revenue")

    otp_code = extract_otp_code_from_message(message_text)
    ts = human_time()

    otp = {
        "originator": originator,
        "recipient": recipient,
        "country_iso": country_iso,
        "range": range_val,
        "limit": limit_flag,
        "revenue": revenue,
        "message": message_text,
        "otp_code": otp_code,
        "time": ts,
    }

    otp_stats["total"] += 1
    ori_key = originator or "(unknown)"
    otp_stats["by_originator"][ori_key] = otp_stats["by_originator"].get(ori_key, 0) + 1
    c_key = country_iso or "(unknown)"
    otp_stats["by_country"][c_key] = otp_stats["by_country"].get(c_key, 0) + 1

    otp_history.append(otp)
    if len(otp_history) > MAX_HISTORY:
        otp_history.pop(0)

    render_otp_panel(otp)
    send_otp_notification(otp)

# ===================== NUMBERS (ON DEMAND) =====================

def fetch_numbers_groups(sess: requests.Session, active_cookies: dict):
    """
    Return:
      groups: { range_name: {number, ...} }
      ids_by_group: { range_name: [number_id,...] }
    Single "bulk" fetch using server-side pagination.
    """
    groups = {}
    ids_by_group = {}
    start = 0
    page_size = NUMBERS_PAGE_SIZE
    max_pages = 100  # safety

    while True:
        params = {
            "draw": 1,
            "columns[0][data]": "number_id",
            "columns[0][name]": "id",
            "columns[0][orderable]": "false",
            "columns[1][data]": "Number",
            "columns[2][data]": "range",
            "columns[3][data]": "A2P",
            "columns[4][data]": "P2P",
            "columns[5][data]": "LimitA2P",
            "columns[6][data]": "limit_cli_a2p",
            "columns[7][data]": "limit_did_a2p",
            "columns[8][data]": "limit_cli_did_a2p",
            "columns[9][data]": "LimitP2P",
            "columns[10][data]": "limit_cli_p2p",
            "columns[11][data]": "limit_did_p2p",
            "columns[12][data]": "limit_cli_did_p2p",
            "columns[13][data]": "action",
            "columns[13][searchable]": "false",
            "columns[13][orderable]": "false",
            "order[0][column]": 1,
            "order[0][dir]": "desc",
            "start": start,
            "length": page_size,
            "search[value]": "",
        }

        r = sess.get(
            NUMBERS_BASE_URL,
            headers=NUMBERS_HEADERS,
            cookies=active_cookies,
            params=params,
            timeout=(NUMBERS_CONNECT_TIMEOUT, NUMBERS_READ_TIMEOUT),
            allow_redirects=False,
        )
        if r.status_code in (301, 302, 303, 307, 308):
            raise RuntimeError("Redirected (cookies/CSRF likely expired).")
        r.raise_for_status()
        j = r.json()

        rows = j.get("data", []) or []
        records_total = j.get("recordsTotal") or j.get("recordsFiltered")
        try:
            records_total = int(records_total)
        except Exception:
            records_total = None

        for row in rows:
            num_raw = row.get("Number")
            num = str(num_raw).strip() if num_raw is not None else ""
            rng = str(row.get("range") or "Unknown").strip()

            num_id_html = row.get("number_id") or ""
            m = re.search(r'value="(\d+)"', num_id_html)
            num_id = m.group(1) if m else None

            if not num:
                continue

            groups.setdefault(rng, set()).add(num)
            if num_id:
                ids_by_group.setdefault(rng, []).append(num_id)

        if not rows:
            break
        start += page_size
        if records_total is not None and start >= records_total:
            break
        if start >= page_size * max_pages:
            break

    return groups, ids_by_group


def refresh_numbers_now():
    """
    Fetch numbers ON DEMAND.
    Called only when user taps 'Numbers' or 'Choose Range' in Telegram.
    """
    global numbers_groups, numbers_ids_by_group, numbers_last_update, numbers_total_numbers, numbers_error
    sess = requests.Session()
    try:
        active_cookies = get_live_cookies()
        groups, ids_by_group = fetch_numbers_groups(sess, active_cookies)
        now = time.time()
        numbers_groups = groups
        numbers_ids_by_group = ids_by_group
        numbers_last_update = now
        numbers_total_numbers = sum(len(s) for s in groups.values())
        numbers_error = None
        log(
            f"Numbers fetched ON DEMAND: {len(groups)} ranges, {numbers_total_numbers} numbers.",
            "OK",
        )
        _alert_state["numbers"] = None
        return True, None
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            numbers_error = "Blocked by Cloudflare on /portal/numbers. Solve it in browser; cookies will update."
            send_or_edit_alert(
                "numbers",
                "ACTIVE",
                numbers_error,
            )
        else:
            numbers_error = f"{type(e).__name__}: {e}"
        log(f"Numbers fetch error (on demand): {numbers_error}", "WARN")
        return False, numbers_error
    except Exception as e:
        numbers_error = f"{type(e).__name__}: {e}"
        log(f"Numbers fetch error (on demand): {numbers_error}", "WARN")
        return False, numbers_error

# ===================== CSRF + COOKIES FOR REQUESTS =====================

def get_active_cookies_and_csrf():
    """
    Get current cookies + CSRF token from in-memory variables.
    Cookies:
      - from browser (current_cookies)
      - fallback: backup file / static cookies
    CSRF:
      - only from current_csrf_token (HTML extracted)
    """
    active = get_live_cookies()
    csrf = current_csrf_token or ""
    return active, csrf

# ===================== ADD NUMBER (ON DEMAND, CSRF AWARE) =====================

def add_number_by_id(term_id: str | int) -> tuple[bool, str]:
    """
    Call /portal/numbers/termination/number/add with current cookies + CSRF.
    Returns (ok: bool, message: str). No token printed.
    """
    sess = requests.Session()
    active_cookies, csrf = get_active_cookies_and_csrf()

    if not csrf:
        return False, "No CSRF token in memory. Open numbers or live SMS page in browser so script can capture it."

    data = {
        "_token": csrf,
        "id": str(term_id),
    }

    headers = dict(NUMBERS_HEADERS)
    headers["Referer"] = "https://www.ivasms.com/portal/numbers"
    headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"

    try:
        r = sess.post(
            "https://www.ivasms.com/portal/numbers/termination/number/add",
            cookies=active_cookies,
            headers=headers,
            data=data,
            timeout=(NUMBERS_CONNECT_TIMEOUT, NUMBERS_READ_TIMEOUT),
            allow_redirects=False,
        )

        if r.status_code in (301, 302, 303, 307, 308):
            return False, "Redirected (likely logged out or blocked by Cloudflare)."

        if r.status_code == 403:
            return False, "403 Forbidden (Cloudflare or CSRF). Solve it in browser and try again."

        r.raise_for_status()

        try:
            j = r.json()
            msg = j.get("message") or str(j)
        except Exception:
            msg = r.text[:200]

        return True, msg

    except requests.exceptions.ReadTimeout:
        return False, "ReadTimeout: server took too long to respond while adding number."
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

# ===================== REMOVE NUMBERS BY RANGE =====================

def remove_numbers_for_range(range_name: str) -> tuple[bool, str]:
    """
    Remove all numbers for given range_name using cached NumberID[].
    POST to /portal/numbers/return/number/bluck with:
        _token, NumberID[]=...
    """
    sess = requests.Session()
    active_cookies, csrf = get_active_cookies_and_csrf()

    if not csrf:
        return False, "No CSRF token in memory. Open numbers or live SMS page in browser so script can capture it."

    ids = numbers_ids_by_group.get(range_name)
    if not ids:
        return False, f"No cached NumberID[] for '{range_name}'. Press 📋 Numbers or 🔎 Choose Range first so script can fetch them."

    data_pairs = [("_token", csrf)]
    for nid in ids:
        data_pairs.append(("NumberID[]", str(nid)))

    headers = dict(NUMBERS_HEADERS)
    headers["Referer"] = "https://www.ivasms.com/portal/numbers"
    headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"

    try:
        r = sess.post(
            "https://www.ivasms.com/portal/numbers/return/number/bluck",
            cookies=active_cookies,
            headers=headers,
            data=data_pairs,
            timeout=(NUMBERS_CONNECT_TIMEOUT, NUMBERS_READ_TIMEOUT),
            allow_redirects=False,
        )

        if r.status_code in (301, 302, 303, 307, 308):
            return False, "Redirected (likely logged out or blocked by Cloudflare)."

        if r.status_code in (403, 419):
            return False, f"{r.status_code} error (likely CSRF/Cloudflare). Solve it in browser and press 📋 Numbers again."

        r.raise_for_status()

        try:
            j = r.json()
            msg = j.get("message") or str(j)
        except Exception:
            msg = r.text[:200]

        return True, msg

    except requests.exceptions.ReadTimeout:
        return False, "ReadTimeout: server took too long to respond while removing numbers."
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

# ===================== TELEGRAM UI =====================

def main_menu_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "📋 Numbers",       "callback_data": "menu:numbers"},
                {"text": "🔎 Choose Range",  "callback_data": "menu:groups"},
            ],
            [
                {"text": "➕ Add Number",    "callback_data": "menu:addnum"},
                {"text": "🗑 Remove Numbers","callback_data": "menu:rmrange"},
            ],
            [
                {"text": "📊 OTP Stats",     "callback_data": "stats"},
                {"text": "📜 OTP History",   "callback_data": "history"},
            ],
            [
                {"text": "🔧 Status",        "callback_data": "status"},
            ],
        ]
    }


def is_admin(chat_id: str) -> bool:
    return str(chat_id).strip() == str(TELEGRAM_ADMIN_CHAT_ID).strip()


def draw_numbers_all(page: int = 1):
    if not numbers_groups:
        return "⚠️ No numbers fetched yet. Press 📋 Numbers again after login is valid.", main_menu_keyboard()
    parts = []
    for grp in sorted(numbers_groups):
        nums = [plusify(n) for n in sorted(numbers_groups[grp])]
        parts.append(f"• {grp} ({len(nums)}):")
        parts.extend(nums)
    page_lines, total_pages = chunk_lines(parts, page, PAGE_SIZE)
    text = "📋 Current Numbers (all)\n\n" + "\n".join(page_lines)
    nav = []
    if total_pages > 1:
        nav = [
            {"text": "« 1",                   "callback_data": "nav:all:1"},
            {"text": "‹",                     "callback_data": f"nav:all:{max(1, page-1)}"},
            {"text": f"{page}/{total_pages}", "callback_data": "noop"},
            {"text": "›",                     "callback_data": f"nav:all:{min(total_pages, page+1)}"},
            {"text": f"{total_pages} »",      "callback_data": f"nav:all:{total_pages}"},
        ]
    rows = []
    if nav:
        rows.append(nav)
    rows.append([{"text": "🔙 Menu", "callback_data": "menu:home"}])
    return text, {"inline_keyboard": rows}


def list_groups(page: int = 1, mode: str = "view"):
    """
    mode:
      "view"   -> callback_data = group:{name}:1 (view numbers)
      "remove" -> callback_data = rmgroup:{name} (remove confirm)
    """
    groups = sorted(numbers_groups.keys()) if numbers_groups else []
    if not groups:
        return "⚠️ No ranges fetched yet. Press 📋 Numbers again after login is valid.", main_menu_keyboard()
    page_items, total_pages = chunk_lines(groups, page, 12)
    rows = []
    row = []
    for g in page_items:
        if mode == "view":
            cb = f"group:{g}:1"
        else:
            cb = f"rmgroup:{g}"
        row.append({"text": g, "callback_data": cb})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if total_pages > 1:
        if mode == "view":
            prefix = "nav:groups"
        else:
            prefix = "nav:rmgroups"
        nav = [
            {"text": "« 1",                  "callback_data": f"{prefix}:1"},
            {"text": "‹",                    "callback_data": f"{prefix}:{max(1, page-1)}"},
            {"text": f"{page}/{total_pages}","callback_data": "noop"},
            {"text": "›",                    "callback_data": f"{prefix}:{min(total_pages, page+1)}"},
            {"text": f"{total_pages} »",     "callback_data": f"{prefix}:{total_pages}"},
        ]
        rows.append(nav)
    rows.append([{"text": "🔙 Menu", "callback_data": "menu:home"}])

    title = "🔎 Choose a range:" if mode == "view" else "🗑 Choose a range to REMOVE all its numbers:"
    return title, {"inline_keyboard": rows}


def draw_one_group(group_name: str, page: int = 1):
    nums = sorted(numbers_groups.get(group_name, []))
    if not nums:
        kb = {
            "inline_keyboard": [
                [{"text": "🔙 Back", "callback_data": "menu:groups"}],
                [{"text": "🔙 Menu", "callback_data": "menu:home"}],
            ]
        }
        return f"⚠️ No numbers under “{group_name}”.", kb
    pnums = [plusify(n) for n in nums]
    page_nums, total_pages = chunk_lines(pnums, page, PAGE_SIZE)
    text = f"📂 {group_name} — {len(nums)} numbers\n\n" + "\n".join(page_nums)
    rows = []
    if total_pages > 1:
        nav = [
            {"text": "« 1",                   "callback_data": f"nav:group:{group_name}:1"},
            {"text": "‹",                     "callback_data": f"nav:group:{group_name}:{max(1, page-1)}"},
            {"text": f"{page}/{total_pages}", "callback_data": "noop"},
            {"text": "›",                     "callback_data": f"nav:group:{group_name}:{min(total_pages, page+1)}"},
            {"text": f"{total_pages} »",      "callback_data": f"nav:group:{group_name}:{total_pages}"},
        ]
        rows.append(nav)
    rows.append([
        {"text": "🔙 Back", "callback_data": "menu:groups"},
        {"text": "🔙 Menu", "callback_data": "menu:home"},
    ])
    return text, {"inline_keyboard": rows}


def handle_callback_query(callback: dict):
    try:
        data = callback.get("data", "")
        msg = callback.get("message", {}) or {}
        chat = msg.get("chat", {}) or {}
        chat_id = str(chat.get("id") or callback.get("from", {}).get("id"))

        def ack(text: str | None = None):
            payload = {"callback_query_id": callback.get("id")}
            if text:
                payload["text"] = text
            telegram_api_call("answerCallbackQuery", payload)

        if not is_admin(chat_id):
            ack("Unauthorized")
            send_telegram_raw(chat_id, "❌ Unauthorized — only admin can use this UI.")
            return

        if data == "noop":
            ack()
            return

        if data == "menu:home":
            ack("Menu")
            addnum_pending.discard(chat_id)
            rmrange_select_pending.discard(chat_id)
            rmrange_confirm_for_chat.pop(chat_id, None)
            send_telegram_raw(chat_id, "🏠 Menu", reply_markup=main_menu_keyboard())
            return

        if data == "menu:numbers":
            ack("Numbers")
            addnum_pending.discard(chat_id)
            rmrange_select_pending.discard(chat_id)
            rmrange_confirm_for_chat.pop(chat_id, None)
            ok, err = refresh_numbers_now()
            if not ok:
                txt = (
                    "⚠️ Could not fetch numbers right now.\n\n"
                    f"<code>{html.escape(str(err))}</code>\n\n"
                    "If it's Cloudflare, solve it once in the browser window."
                )
                send_telegram_raw(chat_id, txt, parse_mode="HTML", reply_markup=main_menu_keyboard())
                return
            text, markup = draw_numbers_all(1)
            send_telegram_raw(chat_id, text, reply_markup=markup)
            return

        if data == "menu:groups":
            ack("Ranges")
            addnum_pending.discard(chat_id)
            rmrange_select_pending.discard(chat_id)
            rmrange_confirm_for_chat.pop(chat_id, None)
            ok, err = refresh_numbers_now()
            if not ok:
                txt = (
                    "⚠️ Could not fetch numbers right now.\n\n"
                    f"<code>{html.escape(str(err))}</code>\n\n"
                    "If it's Cloudflare, solve it once in the browser window."
                )
                send_telegram_raw(chat_id, txt, parse_mode="HTML", reply_markup=main_menu_keyboard())
                return
            text, markup = list_groups(1, mode="view")
            send_telegram_raw(chat_id, text, reply_markup=markup)
            return

        if data == "menu:addnum":
            ack("Add Number")
            addnum_pending.add(chat_id)
            rmrange_select_pending.discard(chat_id)
            rmrange_confirm_for_chat.pop(chat_id, None)
            kb = {
                "inline_keyboard": [
                    [{"text": "❌ Cancel", "callback_data": "addnum:cancel"}],
                    [{"text": "🔙 Menu", "callback_data": "menu:home"}],
                ]
            }
            send_telegram_raw(
                chat_id,
                "➕ Send the termination ID you want to add (e.g. <code>980693</code>):",
                parse_mode="HTML",
                reply_markup=kb,
            )
            return

        if data == "addnum:cancel":
            ack("Cancelled")
            addnum_pending.discard(chat_id)
            send_telegram_raw(
                chat_id,
                "Add Number cancelled.",
                reply_markup=main_menu_keyboard(),
            )
            return

        if data == "menu:rmrange":
            ack("Remove Numbers")
            addnum_pending.discard(chat_id)
            rmrange_confirm_for_chat.pop(chat_id, None)
            ok, err = refresh_numbers_now()
            if not ok:
                txt = (
                    "⚠️ Could not fetch numbers right now.\n\n"
                    f"<code>{html.escape(str(err))}</code>\n\n"
                    "If it's Cloudflare, solve it once in the browser window."
                )
                send_telegram_raw(chat_id, txt, parse_mode="HTML", reply_markup=main_menu_keyboard())
                return
            rmrange_select_pending.add(chat_id)
            text, markup = list_groups(1, mode="remove")
            send_telegram_raw(chat_id, text, reply_markup=markup)
            return

        if data.startswith("nav:all:"):
            page = int(data.split(":")[2])
            ack("Page")
            text, markup = draw_numbers_all(page)
            send_telegram_raw(chat_id, text, reply_markup=markup)
            return

        if data.startswith("nav:groups:"):
            page = int(data.split(":")[2])
            ack("Page")
            text, markup = list_groups(page, mode="view")
            send_telegram_raw(chat_id, text, reply_markup=markup)
            return

        if data.startswith("nav:rmgroups:"):
            page = int(data.split(":")[2])
            ack("Page")
            text, markup = list_groups(page, mode="remove")
            send_telegram_raw(chat_id, text, reply_markup=markup)
            return

        if data.startswith("group:"):
            _, grp, page = data.split(":", 2)
            page = int(page)
            ack(grp)
            text, markup = draw_one_group(grp, page)
            send_telegram_raw(chat_id, text, reply_markup=markup)
            return

        if data.startswith("nav:group:"):
            _, _, grp, page = data.split(":", 3)
            page = int(page)
            ack("Page")
            text, markup = draw_one_group(grp, page)
            send_telegram_raw(chat_id, text, reply_markup=markup)
            return

        if data.startswith("rmgroup:"):
            _, grp = data.split(":", 1)
            ack("Confirm remove")
            rmrange_select_pending.discard(chat_id)
            rmrange_confirm_for_chat[chat_id] = grp

            count_ids = len(numbers_ids_by_group.get(grp, []) or [])
            text = (
                f"🗑 Do you want to remove <b>{count_ids}</b> numbers from "
                f"<b>{html.escape(grp)}</b>?\n\n"
                "This sends all NumberID[] for that range to the server."
            )
            kb = {
                "inline_keyboard": [
                    [
                        {"text": "✅ Yes, remove", "callback_data": "rmrange:confirm"},
                        {"text": "❌ Cancel",       "callback_data": "rmrange:cancel"},
                    ],
                    [{"text": "🔙 Menu", "callback_data": "menu:home"}],
                ]
            }
            send_telegram_raw(chat_id, text, parse_mode="HTML", reply_markup=kb)
            return

        if data == "rmrange:cancel":
            ack("Cancelled")
            rmrange_confirm_for_chat.pop(chat_id, None)
            send_telegram_raw(
                chat_id,
                "Remove Numbers cancelled.",
                reply_markup=main_menu_keyboard(),
            )
            return

        if data == "rmrange:confirm":
            ack("Removing")
            grp = rmrange_confirm_for_chat.pop(chat_id, None)
            if not grp:
                send_telegram_raw(
                    chat_id,
                    "No range selected to remove.",
                    reply_markup=main_menu_keyboard(),
                )
                return

            ok, msg = remove_numbers_for_range(grp)
            if ok:
                reply = (
                    f"✅ Removed numbers from <b>{html.escape(grp)}</b>.\n\n"
                    f"Server: <code>{html.escape(msg)}</code>"
                )
            else:
                reply = (
                    f"❌ Failed to remove numbers from <b>{html.escape(grp)}</b>.\n"
                    f"<code>{html.escape(msg)}</code>"
                )
            send_telegram_raw(chat_id, reply, parse_mode="HTML", reply_markup=main_menu_keyboard())
            return

        if data == "stats":
            ack("Stats")
            addnum_pending.discard(chat_id)
            rmrange_select_pending.discard(chat_id)
            rmrange_confirm_for_chat.pop(chat_id, None)
            send_telegram_raw(
                chat_id,
                handle_text_command_and_return(chat_id, "/stats"),
                parse_mode="HTML",
            )
            return

        if data == "history":
            ack("History")
            addnum_pending.discard(chat_id)
            rmrange_select_pending.discard(chat_id)
            rmrange_confirm_for_chat.pop(chat_id, None)
            send_telegram_raw(
                chat_id,
                handle_text_command_and_return(chat_id, "/history"),
                parse_mode="HTML",
            )
            return

        if data == "status":
            ack("Status")
            addnum_pending.discard(chat_id)
            rmrange_select_pending.discard(chat_id)
            rmrange_confirm_for_chat.pop(chat_id, None)
            send_telegram_raw(
                chat_id,
                handle_text_command_and_return(chat_id, "/status"),
                parse_mode="HTML",
            )
            return

        ack("Unknown")
    except Exception as e:
        log(f"Error handling callback: {e}", "ERROR")
        traceback.print_exc()


def handle_text_command_and_return(chat_id: str, text: str) -> str:
    if not is_admin(chat_id):
        return "❌ Unauthorized — you are not the admin."
    parts = text.strip().split()
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd == "/stats":
        total = otp_stats["total"]
        if total == 0:
            return "📊 No OTPs received yet."
        lines = [f"Total OTPs: <b>{total}</b>\n"]
        if otp_stats["by_originator"]:
            lines.append("By originator:")
            for ori, cnt in sorted(
                otp_stats["by_originator"].items(), key=lambda x: x[1], reverse=True
            )[:20]:
                lines.append(f"• <code>{html.escape(str(ori))}</code> — {cnt}")
        if otp_stats["by_country"]:
            lines.append("\nBy country:")
            for cc, cnt in sorted(
                otp_stats["by_country"].items(), key=lambda x: x[1], reverse=True
            )[:20]:
                lines.append(f"• <code>{html.escape(str(cc))}</code> — {cnt}")
        return "📊 OTP Stats\n" + "\n".join(lines)

    if cmd == "/history":
        n = 10
        if args and args[0].isdigit():
            n = max(1, min(100, int(args[0])))
        if not otp_history:
            return "📜 No history yet."
        items = otp_history[-n:][::-1]
        lines = []
        for o in items:
            originator = html.escape(str(o.get("originator") or "-"))
            recipient  = html.escape(str(o.get("recipient")  or "-"))
            code       = html.escape(str(o.get("otp_code")    or "-"))
            ts         = html.escape(str(o.get("time")        or "-"))
            lines.append(
                f"• [{ts}] <code>{originator}</code> → <code>{recipient}</code> — OTP: <code>{code}</code>"
            )
        return "📜 Recent OTPs:\n" + "\n".join(lines)

    if cmd == "/status":
        connected = _state.get("connected", False)
        last_http = _state.get("last_http_ok")
        last_http_human = human_time(last_http) if last_http else "never"
        total = otp_stats["total"]

        if otp_history:
            last = otp_history[-1]
            last_summary = (
                f"Last OTP: <code>{html.escape(str(last.get('otp_code') or '-'))}</code> "
                f"from <code>{html.escape(str(last.get('originator') or '-'))}</code> "
                f"to <code>{html.escape(str(last.get('recipient') or '-'))}</code> "
                f"at {html.escape(str(last.get('time') or '-'))}"
            )
        else:
            last_summary = "Last OTP: none yet."

        num_ranges = len(numbers_groups) if numbers_groups else 0
        num_total  = numbers_total_numbers
        if numbers_last_update:
            ago = human_duration(time.time() - numbers_last_update)
            numbers_info = f"Numbers: {num_total} across {num_ranges} ranges (last fetch {ago} ago)"
        else:
            if numbers_error:
                numbers_info = f"Numbers: error ({html.escape(str(numbers_error))})"
            else:
                numbers_info = "Numbers: not fetched yet (tap 📋 Numbers / 🔎 Choose Range)."

        return (
            f"🔧 Status\n"
            f"• Connected: {str(connected)}\n"
            f"• Last HTTP OK: {html.escape(str(last_http_human))}\n"
            f"• Total OTPs: {total}\n"
            f"• {last_summary}\n"
            f"• {numbers_info}"
        )

    if cmd in ("/addnum", "/addnumber", "/add"):
        if not args:
            return "Usage: <code>/addnum TERMINATION_ID</code>\nExample: <code>/addnum 980693</code>"

        term_id = args[0]
        ok, msg = add_number_by_id(term_id)

        if ok:
            return (
                "✅ Add Number request sent.\n"
                f"ID: <code>{html.escape(str(term_id))}</code>\n"
                f"Server: <code>{html.escape(str(msg))}</code>"
            )
        else:
            return (
                "❌ Failed to add number.\n"
                f"ID: <code>{html.escape(str(term_id))}</code>\n\n"
                f"<code>{html.escape(str(msg))}</code>"
            )

    if cmd in ("/rmrange", "/removerange", "/rm"):
        if not args:
            return "Usage: <code>/rmrange RANGE_NAME</code>\nExample: <code>/rmrange JAMAICA 68</code>"
        grp = " ".join(args)
        ok, msg = remove_numbers_for_range(grp)
        if ok:
            return (
                f"✅ Removed numbers from <b>{html.escape(grp)}</b>.\n"
                f"Server: <code>{html.escape(msg)}</code>"
            )
        else:
            return (
                f"❌ Failed to remove numbers from <b>{html.escape(grp)}</b>.\n"
                f"<code>{html.escape(msg)}</code>"
            )

    return "❓ Unknown command. Use /menu or buttons."


def telegram_poll_loop():
    global _LAST_UPDATE_ID
    token = TELEGRAM_BOT_TOKEN.strip()
    if not token:
        log("Telegram token not configured — UI disabled.", "WARN")
        return
    base = f"https://api.telegram.org/bot{token}"
    get_updates_url = base + "/getUpdates"
    log("Telegram poller started.", "INFO")
    while True:
        try:
            params = {
                "timeout": TELEGRAM_POLL_TIMEOUT,
                "allowed_updates": ["message", "callback_query"],
            }
            if _LAST_UPDATE_ID is not None:
                params["offset"] = _LAST_UPDATE_ID + 1
            r = requests.get(get_updates_url, params=params, timeout=TELEGRAM_POLL_TIMEOUT + 10)
            data = r.json() if r.status_code == 200 else {}
            if not data.get("ok"):
                time.sleep(2)
                continue
            for upd in data.get("result", []):
                _LAST_UPDATE_ID = upd.get("update_id", _LAST_UPDATE_ID)

                if "callback_query" in upd:
                    handle_callback_query(upd["callback_query"])
                    continue

                msg = upd.get("message") or upd.get("edited_message") or {}
                if not msg:
                    continue
                chat = msg.get("chat", {})
                chat_id = str(chat.get("id"))
                text = msg.get("text", "") or ""

                if chat_id in addnum_pending and not text.strip().startswith("/"):
                    term_id = text.strip().split()[0]
                    ok, res_msg = add_number_by_id(term_id)
                    addnum_pending.discard(chat_id)

                    if ok:
                        reply = (
                            "✅ Add Number request sent.\n"
                            f"ID: <code>{html.escape(str(term_id))}</code>\n"
                            f"Server: <code>{html.escape(str(res_msg))}</code>"
                        )
                    else:
                        reply = (
                            "❌ Failed to add number.\n"
                            f"ID: <code>{html.escape(str(term_id))}</code>\n\n"
                            f"<code>{html.escape(str(res_msg))}</code>"
                        )
                    send_telegram_raw(chat_id, reply, parse_mode="HTML", reply_markup=main_menu_keyboard())
                    continue

                if text.strip().startswith("/"):
                    cmd = text.strip().split()[0].lower()
                    if cmd in ("/menu", "/start"):
                        addnum_pending.discard(chat_id)
                        rmrange_select_pending.discard(chat_id)
                        rmrange_confirm_for_chat.pop(chat_id, None)
                        send_telegram_raw(
                            chat_id,
                            "Select an action:",
                            reply_markup=main_menu_keyboard(),
                        )
                    else:
                        resp = handle_text_command_and_return(chat_id, text.strip())
                        send_telegram_raw(chat_id, resp, parse_mode="HTML")
                    continue

                if text.strip().lower() in ("menu", "buttons", "ui"):
                    addnum_pending.discard(chat_id)
                    rmrange_select_pending.discard(chat_id)
                    rmrange_confirm_for_chat.pop(chat_id, None)
                    send_telegram_raw(
                        chat_id,
                        "Select an action:",
                        reply_markup=main_menu_keyboard(),
                    )
                    continue

                if is_admin(chat_id):
                    send_telegram_raw(
                        chat_id,
                        "Use buttons or /menu.",
                        reply_markup=main_menu_keyboard(),
                    )
            time.sleep(0.5)
        except Exception as e:
            log(f"Telegram poll error: {e}", "WARN")
            traceback.print_exc()
            time.sleep(3)

# ===================== TOKEN FETCH & WS RUN =====================

def build_headers(cookie_string: str) -> list:
    return [
        "Host: ivasms.com",
        "Origin: https://www.ivasms.com",
        f"User-Agent: {HTTP_HEADERS.get('User-Agent')}",
        f"Cookie: {cookie_string}",
    ]


def fetch_token_and_user(driver) -> tuple[str, str]:
    """
    Extract livesms token + user from the *current* browser page.

    ❗ IMPORTANT:
      - NO driver.get() here (NO refresh).
      - NO requests.get() here.
      - If current page is Cloudflare or doesn't contain token/user → raise,
        so run_ws() can just sleep & retry without touching the browser.

    Used by run_ws(driver) only.
    """
    if driver is None:
        raise RuntimeError("fetch_token_and_user() needs a live Selenium driver.")

    # Read whatever page is currently open (no navigation)
    try:
        html_page = driver.page_source
    except Exception as e:
        raise RuntimeError(f"Could not read page source from browser: {e}")

    # If it's Cloudflare, don't try to be smart here.
    if looks_like_cloudflare(html_page):
        raise RuntimeError("Browser is on Cloudflare challenge page. Solve it manually.")

    # Update CSRF token in memory (if present in this page)
    maybe_update_csrf_from_html(html_page)

    token = None
    user = None

    # Same pattern you were using before
    pattern = (
        r"io\.connect\('https://ivasms\.com:2087/livesms',\s*\{\s*query\s*:\s*\{\s*"
        r"token:\s*'([^']+)'[^}]*user:\"([^\"}]+)\""
    )
    m = re.search(pattern, html_page, re.DOTALL)
    if m:
        token = m.group(1).strip()
        user  = m.group(2).strip()

    # Fallback: looser token/user search
    if not (token and user):
        m_token = re.search(r"token['\"]?\s*:\s*['\"]([^'\"<>]+)['\"]", html_page)
        m_user  = re.search(r"user['\"]?\s*:\s*['\"]([^'\"<>]+)['\"]",  html_page)
        if m_token and m_user:
            token = token or m_token.group(1).strip()
            user  = user  or m_user.group(1).strip()

    if not token or not user:
        raise RuntimeError("Could not find livesms token/user in current page HTML.")

    log(f"Extracted livesms token via browser (len={len(token)}), user={user}", "OK")
    return token, user

# ===================== 403 HANDLING DURING WS (BACKUP) =====================

def handle_http_403_during_ws(driver, url: str | None, reason: str):
    """
    Called ONLY when the HTTP validation for livesms returns 403
    AND the response HTML already looked like Cloudflare.

    Behavior:
      - First time:
          * logs + alert
          * opens LIVE_SMS_URL in browser ONCE
          * updates CSRF
          * if the BROWSER page is still Cloudflare -> run GUI solver once
      - Later 403s:
          * this function WON'T run again (guard), so no more refresh spam
    """
    try:
        # one-shot guard: only do full recovery once per script run
        if not hasattr(handle_http_403_during_ws, "_did_recover"):
            handle_http_403_during_ws._did_recover = False

        if handle_http_403_during_ws._did_recover or driver is None:
            # Already tried recovery once; nothing more to do.
            log("403 recovery already attempted earlier; skipping browser refresh.", "WARN")
            return

        handle_http_403_during_ws._did_recover = True

        base_msg = f"HTTP 403 from {url or 'unknown URL'} (Cloudflare detected in HTTP body)."
        msg = (
            base_msg + "\n"
            "Opening Live SMS page in browser ONCE to refresh and try auto-solve..."
        )
        log(msg, "WARN")
        send_or_edit_alert(
            "session",
            "ACTIVE",
            f"HTTP 403 on livesms HTTP check at {url or 'unknown'} "
            "(looks like Cloudflare).\n"
            "Browser page is being opened once to try recovery.",
        )

        # Open page once
        driver.get(LIVE_SMS_URL)
        time.sleep(3)

        try:
            html_page = driver.page_source
            curr_url = driver.current_url.lower()
        except Exception:
            html_page = ""
            curr_url = ""

        # Update CSRF from page HTML
        maybe_update_csrf_from_html(html_page)

        # If browser page is still Cloudflare, run GUI solver once
        if looks_like_cloudflare(html_page):
            send_or_edit_alert(
                "cloudflare",
                "ACTIVE",
                "Cloudflare is visible in the browser while recovering from HTTP 403. "
                "Waiting 6s, then trying GUI auto-solve once...",
            )
            time.sleep(6)
            attempted = attempt_cloudflare_auto_solve(driver)
            time.sleep(2)

            try:
                html_after = driver.page_source
            except Exception:
                html_after = ""

            if not looks_like_cloudflare(html_after):
                send_or_edit_alert(
                    "cloudflare",
                    "RESOLVED",
                    "Cloudflare cleared after auto-solve (403 recovery).",
                )
            else:
                if attempted:
                    send_or_edit_alert(
                        "cloudflare",
                        "FAILED",
                        "Auto-solve failed during 403 recovery. "
                        "Please click the Cloudflare checkbox manually in the browser.",
                    )
                else:
                    send_or_edit_alert(
                        "cloudflare",
                        "FAILED",
                        "Cloudflare present during 403 recovery but GUI auto-solve "
                        "could not run (already used). Please solve manually.",
                    )
        else:
            # No CF in browser page now → maybe login page or something else
            if "login" in curr_url:
                send_or_edit_alert(
                    "session",
                    "ACTIVE",
                    "Session appears lost (login page) after 403. "
                    "Please log in again in the browser window.",
                )

    except Exception as e:
        log(f"Error in handle_http_403_during_ws: {e}", "ERROR")
        traceback.print_exc()

# ===================== WS MAIN LOOP =====================

def build_ws_url(token: str, user: str) -> str:
    base = WS_BASE.rstrip("/")
    return (
        f"{base}/?token={quote_plus(token)}"
        f"&user={quote_plus(user)}"
        f"&EIO=4&transport=websocket"
    )


def run_ws(driver):
    """
    PURE WebSocket loop:

    - Token + user only from browser (fetch_token_and_user(driver)).
    - Cookies only from live Selenium session (snapshot_cookies), with backup fallback.
    - NO HTTP validation via requests.
    - NO auto-refresh, NO Cloudflare handler here.
    """
    backoff = 2

    while True:
        # 1) Token + user from browser
        try:
            token, user = fetch_token_and_user(driver)
            _state["last_http_ok"] = time.time()
            log("Browser validation OK (token + user).", "OK")
            backoff = 2
        except Exception as e:
            log(f"Browser token fetch failed: {e}", "ERROR")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue

        # 2) Cookies from browser (fallback → backup)
        try:
            _, simple_cookies = snapshot_cookies(driver)
            cookie_header = "; ".join(f"{k}={v}" for k, v in simple_cookies.items() if v)
        except Exception as e:
            log(f"Cookie snapshot failed, using backup cookies: {e}", "WARN")
            backup = get_live_cookies()
            cookie_header = "; ".join(f"{k}={v}" for k, v in backup.items() if v)

        # 3) Connect WS
        ws_url = build_ws_url(token, user)
        log(f"Connecting WebSocket → {ws_url}", "INFO")

        try:
            ws = websocket.WebSocketApp(
                ws_url,
                header=build_headers(cookie_header),
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )

            # No browser refresh here, ever
            ws.run_forever(
                ping_interval=25,
                ping_timeout=10,
                sslopt={"check_hostname": False},
            )

        except KeyboardInterrupt:
            log("Interrupted manually. Stopping WS.", "INFO")
            return
        except Exception as exc:
            log(f"run_ws exception: {exc}", "ERROR")
            traceback.print_exc()

        # 4) Retry on close
        time.sleep(backoff)
        backoff = min(backoff * 2, 60)

# ===================== MAIN =====================

if __name__ == "__main__":
    import re as _re

    print("\n" + TOP)
    intro = f" {EMOJI_FIRE} IVASMS All-in-One: Login + OTP + Numbers + Add/Remove (Telegram UI)"
    pad = WIDTH - 4 - len(_re.sub(r"\x1b\[[0-9;]*m", "", intro))
    pad = max(pad, 0)
    print(f"{PURPLE}│{RESET}{GREEN}{intro}{' ' * pad}{PURPLE}│{RESET}")
    info = f" {EMOJI_WHATSAPP}/{EMOJI_TELEGRAM} OTP → Telegram (admin: {TELEGRAM_ADMIN_CHAT_ID})"
    pad2 = WIDTH - 4 - len(_re.sub(r"\x1b\[[0-9;]*m", "", info))
    pad2 = max(pad2, 0)
    print(f"{PURPLE}│{RESET}{CYAN}{info}{' ' * pad2}{PURPLE}│{RESET}")
    print(BOT + "\n")

    check_display()
    driver = setup_driver()
    DRIVER = driver

    try:
        ok = login_process(driver)
        if not ok:
            print("❌ Login aborted.")
            sys.exit(1)

        threading.Thread(target=cookies_monitor_loop, args=(driver,), daemon=True).start()

        if TELEGRAM_BOT_TOKEN.strip() and TELEGRAM_ADMIN_CHAT_ID:
            threading.Thread(target=telegram_poll_loop, daemon=True).start()
        else:
            log("Telegram token or admin chat id missing — UI disabled.", "WARN")

        run_ws(driver)

    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")
    finally:
        try:
            driver.quit()
        except Exception:
            pass
