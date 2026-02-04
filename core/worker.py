import asyncio
import logging
import time
import re
import json
import aiohttp
import socketio
from urllib.parse import urlencode

# SeleniumBase & Stealth
from sb_stealth_wrapper import StealthBot
from sb_stealth_wrapper.strategies.input import HumanInputStrategy

# Config & Utils
from config import IVASMS_LOGIN_URL, IVASMS_BASE_URL, LIVE_SMS_URL, REMOVE_NUMBER_URL
from utils import CountryManager, log

# ====================================================
# 🛠️ YOUR EXACT CLOUDFLARE FUNCTION
# ====================================================
def check_and_solve_cloudflare(bot, url=None):
    """Checks for Cloudflare and solves it if present."""
    sb = bot.sb if hasattr(bot, 'sb') else bot
    
    if url:
        try:
            sb.activate_cdp_mode(url)
            sb.sleep(2)
        except: pass

    title = sb.get_title()
    if "Just a moment" in title or sb.is_element_visible('iframe[src*="cloudflare"]'):
        log("🛡️ Cloudflare Detected - Solving...", "WARN")
        
        try:
            if hasattr(sb, "uc_gui_click_captcha"):
                sb.solve_captcha()
        except: pass
        
        sb.sleep(2)
        
        if "Just a moment" in sb.get_title():
            try:
                if hasattr(sb, "solve_captcha"):
                    sb.solve_captcha()
            except: pass

        if "Just a moment" in sb.get_title():
            try:
                 sb.execute_script("document.elementFromPoint(window.innerWidth/2, window.innerHeight/2).click();")
            except: pass
        
        sb.sleep(2)
        return True
    return False

# ====================================================
# 🛠️ WORKER CLASS
# ====================================================
SOCKET_TOKEN_REGEX = re.compile(
    r"io\.connect\('https://ivasms\.com:2087/livesms',\s*\{\s*query\s*:\s*\{\s*token:\s*'([^']+)'[^}]*user:\"([^\"}]+)\"", 
    re.DOTALL
)

OTP_REGEX = re.compile(r"\b(\d{3,8}(?:-\d{3,8})?)\b")
NUMBER_ID_REGEX = re.compile(r'value="(\d+)"')

class IvasmsWorker:
    def __init__(self, email, password, notification_callback=None):
        self.email = email
        self.password = password
        self.notify_cb = notification_callback
        
        # Browser State
        self.driver = None
        self.sb = None
        self.active = False
        self.force_refresh_cookies = False
        
        # Session Data
        self.cookies = {}
        self.csrf_token = None
        self.user_agent = None
        
        # WebSocket Data
        self.ws_token = None
        self.ws_user = None
        self.sio = socketio.AsyncClient(logger=True, engineio_logger=True, ssl_verify=False)
        
        # Data Storage
        self.all_numbers = []
        self.id_map = {} # Maps Phone Number -> Database ID
        self.groups = {}
        self.countries = {}
        self.otp_history = []
        self.max_history = 50 
        self.stats = {"numbers": 0, "otp_total": 0, "socket": False}

        self._register_socket_events()

    @property
    def sorted_ranges(self):
        """Helper for UI menu sorting"""
        return sorted(self.groups.keys())

    def _register_socket_events(self):
        @self.sio.event(namespace='/livesms')
        async def connect():
            log(f"[{self.email}] ✅ WebSocket Connected!", "OK")
            self.stats["socket"] = True

        @self.sio.event(namespace='/livesms')
        async def disconnect():
            log(f"[{self.email}] ⚠️ WebSocket Disconnected", "WARN")
            self.stats["socket"] = False

        @self.sio.on('*', namespace='/livesms')
        async def catch_all(event, data):
            await self._handle_ws_message(data)

    async def start(self):
        log(f"[{self.email}] 🚀 Starting Worker...", "INFO")
        self.active = True
        
        # 1. Start Browser
        asyncio.create_task(asyncio.to_thread(self._browser_thread))
        # 2. Start Watchdog
        asyncio.create_task(self.credential_watchdog())
        # 3. Start WebSocket
        asyncio.create_task(self.websocket_loop())

    # ====================================================
    # 🛡️ WATCHDOG
    # ====================================================
    async def credential_watchdog(self):
        log(f"[{self.email}] 🛡️ Watchdog Started", "INFO")
        while self.active:
            try:
                if not self.force_refresh_cookies:
                    await self.get_ws_creds_by_request()
                await asyncio.sleep(15)
            except Exception as e:
                log(f"Watchdog Error: {e}", "ERROR")
                await asyncio.sleep(15)

    async def get_ws_creds_by_request(self):
        try:
            url = LIVE_SMS_URL
            async with await self.get_session() as session:
                async with session.get(url, timeout=15) as resp:
                    if resp.status in [403, 503, 401]:
                        log(f"[{self.email}] 🛡️ Watchdog 403. Triggering Solver...", "WARN")
                        self.force_refresh_cookies = True
                        return False

                    html = await resp.text()
                    m = SOCKET_TOKEN_REGEX.search(html)
                    if m:
                        self.ws_token = m.group(1).strip()
                        self.ws_user = m.group(2).strip()
                        return True
        except Exception: pass
        return False

    # ====================================================
    # 🌐 BROWSER
    # ====================================================
    def _browser_thread(self):
        my_input = HumanInputStrategy()
        with StealthBot(headless=False, input_strategy=my_input) as bot:
            self.sb = bot.sb if hasattr(bot, 'sb') else bot
            self.driver = self.sb.driver
            
            log(f"[{self.email}] Opening Login...", "INFO")
            self.sb.open(IVASMS_LOGIN_URL)
            time.sleep(3)
            
            check_and_solve_cloudflare(bot)

            if self.sb.is_element_visible("#card-email"):
                self.sb.type("#card-email", self.email)
                self.sb.type("#card-password", self.password)
                self.sb.click('button[type="submit"]')
                time.sleep(5)

            self.update_cookies_and_tokens()
            log(f"[{self.email}] Browser Ready.", "OK")

            while self.active:
                time.sleep(5)
                
                # WATCHDOG TRIGGER
                if self.force_refresh_cookies:
                    log(f"[{self.email}] 🚨 Watchdog Triggered - Solving...", "WARN")
                    self.sb.open(LIVE_SMS_URL)
                    
                    check_and_solve_cloudflare(bot, LIVE_SMS_URL)
                    self.update_cookies_and_tokens()
                    
                    self.force_refresh_cookies = False
                    log(f"[{self.email}] ✅ Solved.", "OK")

                # Natural Trigger
                if "Just a moment" in self.sb.get_title():
                    check_and_solve_cloudflare(bot)
                
                # Auto-Relogin
                if "login" in self.sb.get_current_url():
                    try:
                        self.sb.type("#card-email", self.email)
                        self.sb.type("#card-password", self.password)
                        self.sb.click('button[type="submit"]')
                    except: pass

                self.update_cookies_and_tokens()

    def update_cookies_and_tokens(self):
        try:
            self.user_agent = self.driver.execute_script("return navigator.userAgent;")
            cookie_list = self.driver.get_cookies()
            self.cookies = {c['name']: c['value'] for c in cookie_list}
            try: self.csrf_token = self.sb.get_attribute('meta[name="csrf-token"]', "content")
            except: pass
        except: pass

    # ====================================================
    # 📡 WEBSOCKET
    # ====================================================
    async def websocket_loop(self):
        while self.active:
            if self.force_refresh_cookies or not self.cookies:
                await asyncio.sleep(5)
                continue

            if not self.ws_token or not self.user_agent:
                await asyncio.sleep(2)
                continue

            try:
                if not self.sio.connected:
                    params = {'token': self.ws_token, 'user': self.ws_user}
                    url = f"https://ivasms.com:2087?{urlencode(params)}"
                    
                    headers = {
                        "User-Agent": self.user_agent,
                        "Origin": "https://www.ivasms.com",
                        "Host": "ivasms.com:2087",
                        "Cookie": "; ".join([f"{k}={v}" for k,v in self.cookies.items()])
                    }

                    await self.sio.connect(
                        url, 
                        namespaces=['/livesms'], 
                        transports=['websocket'], 
                        socketio_path='socket.io',
                        headers=headers
                    )
                    await self.sio.wait()
            except Exception as e:
                err = str(e).lower()
                if "401" in err or "403" in err or "handshake" in err or "rejected" in err:
                    log(f"[{self.email}] 🚨 WS Rejected. Solving...", "WARN")
                    self.ws_token = None
                    self.force_refresh_cookies = True
                await asyncio.sleep(15)

    async def _handle_ws_message(self, data):
        payload = None
        if isinstance(data, dict): payload = data
        elif isinstance(data, list) and len(data) > 0: payload = data[0]

        if payload and isinstance(payload, dict):
            msg_text = payload.get("message", "")
            if msg_text:
                match = OTP_REGEX.search(msg_text)
                otp_code = match.group(1) if match else "---"
                
                otp_data = {
                    "originator": payload.get("originator", "Unknown"),
                    "recipient": payload.get("recipient", "Unknown"),
                    "otp_code": otp_code,
                    "message": msg_text,
                    "country": payload.get("country_iso", "Unknown"),
                    "time": time.time()
                }
                
                self.otp_history.append(otp_data)
                if len(self.otp_history) > self.max_history: self.otp_history.pop(0)
                self.stats["otp_total"] += 1
                
                if self.notify_cb:
                    await self.notify_cb(self.email, otp_data)

    # ====================================================
    # 🔗 API
    # ====================================================
    async def get_session(self):
        headers = {
            "User-Agent": self.user_agent or "Mozilla/5.0",
            "X-CSRF-TOKEN": self.csrf_token or "",
            "X-Requested-With": "XMLHttpRequest"
        }
        return aiohttp.ClientSession(cookies=self.cookies, headers=headers)

    async def sync_numbers(self):
        if not self.cookies: return False
        url = f"{IVASMS_BASE_URL}/portal/numbers"
        params = {
            "draw": "1", "start": "0", "length": "5000",
            "columns[0][data]": "number_id", "columns[1][data]": "Number",
            "columns[2][data]": "range", "search[value]": ""
        }
        try:
            async with await self.get_session() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status in [403, 503, 401]: 
                        self.force_refresh_cookies = True
                        return False
                    
                    data = await resp.json()
                    rows = data.get("data", [])
                    
                    self.all_numbers = []
                    self.id_map = {} 
                    self.groups = {}
                    self.countries = {}
                    
                    for row in rows:
                        num = str(row.get("Number")).strip()
                        rng = row.get("range", "Unknown")
                        
                        # Extract ID for deletion
                        raw_id_html = row.get("number_id", "")
                        id_match = NUMBER_ID_REGEX.search(raw_id_html)
                        if id_match:
                            db_id = id_match.group(1)
                            self.id_map[num] = db_id
                        
                        self.all_numbers.append(num)
                        
                        if rng not in self.groups: self.groups[rng] = []
                        self.groups[rng].append(num)
                        
                        ctry = CountryManager.get_country(num)
                        if ctry not in self.countries: self.countries[ctry] = []
                        self.countries[ctry].append(num)
                        
                    self.stats["numbers"] = len(self.all_numbers)
                    return True
        except: return False

    async def add_numbers(self, termination_names: list, progress_callback=None):
        if not self.csrf_token: return {"success": 0}
        url = ADD_NUMBER_URL
        success_count = 0
        async with await self.get_session() as session:
            for idx, term_id in enumerate(termination_names):
                try:
                    data = {"_token": self.csrf_token, "id": str(term_id)}
                    async with session.post(url, data=data) as resp:
                        if resp.status in [403, 401]: self.force_refresh_cookies = True
                        if resp.status == 200: success_count += 1
                        if progress_callback: await progress_callback(idx+1, len(termination_names), f"Adding: {term_id}")
                        await asyncio.sleep(1.5)
                except: pass
        return {"success": success_count}
    
    async def bulk_delete(self, numbers_list):
        """
        Removes numbers by looking up their IDs and sending a bulk POST request.
        """
        if not self.csrf_token: return False
        
        # 1. Convert Phone Numbers to IDs
        ids_to_delete = []
        for n in numbers_list:
            if n in self.id_map:
                ids_to_delete.append(self.id_map[n])
        
        if not ids_to_delete:
            return False

        # 2. Delete in Chunks
        CHUNK_SIZE = 100
        total_removed = 0
        url = REMOVE_NUMBER_URL
        
        try:
            async with await self.get_session() as session:
                for i in range(0, len(ids_to_delete), CHUNK_SIZE):
                    chunk_ids = ids_to_delete[i:i + CHUNK_SIZE]
                    
                    data = aiohttp.FormData()
                    data.add_field("_token", self.csrf_token)
                    for num_id in chunk_ids:
                        data.add_field("NumberID[]", num_id)

                    async with session.post(url, data=data) as resp:
                        if resp.status == 200:
                            total_removed += len(chunk_ids)
                            await asyncio.sleep(0.5)
                        elif resp.status in [403, 401]:
                            self.force_refresh_cookies = True
                            return False
            
            # 3. Clean up local memory
            if total_removed > 0:
                await self.sync_numbers() 
                
            return True
        except Exception as e:
            log(f"[{self.email}] Bulk Delete Failed: {e}", "ERROR")
            return False
