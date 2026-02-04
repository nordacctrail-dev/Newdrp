import asyncio
import aiohttp
import json
import re
import time
from urllib.parse import urlencode

import state
import config
import core.database as db
from utils import log

# ===================== PARSING LOGIC =====================

CLI_KEYS = [
    "termination_name", "cli", "sender", "from", "source", "origin", 
    "brand", "app", "application", "service", "channel", "display", 
    "term", "termination", "display_name"
]

TERMID_KEYS = [
    "termination_id", "terminationId", "term_id", "termId", "tid", 
    "ter_id", "sender_id", "cli_id", "identity", "id"
]

def try_json(s):
    try:
        return json.loads(s) if isinstance(s, (str, bytes)) else None
    except:
        return None

def find_json_array_in_text(text: str):
    """
    Robust extraction of [ "event", {data} ] from raw Socket.IO frames.
    """
    if not isinstance(text, str): return None
    idx = text.find("[")
    if idx == -1: return None
    
    substr = text[idx:]
    parsed = try_json(substr)
    if isinstance(parsed, list): return parsed
    
    # Fallback: Try finding the closing bracket
    last = substr.rfind("]")
    if last != -1:
        cand = substr[: last + 1]
        parsed = try_json(cand)
        if isinstance(parsed, list): return parsed
    return None

def recursive_find_key(payload, candidate_keys):
    """Deep search for specific keys in nested dictionaries."""
    if isinstance(payload, dict):
        for k, v in payload.items():
            for ck in candidate_keys:
                if k.lower() == ck.lower() and v:
                    return k, v
        for v in payload.values():
            if isinstance(v, (dict, list)):
                r = recursive_find_key(v, candidate_keys)
                if r: return r
    elif isinstance(payload, list):
        for it in payload:
            if isinstance(it, (dict, list)):
                r = recursive_find_key(it, candidate_keys)
                if r: return r
    return None

def extract_termid_from_payload(payload):
    """Extracts the ID required to BUY the number."""
    r = recursive_find_key(payload, TERMID_KEYS)
    if r: return str(r[1])
    
    if isinstance(payload, dict):
        for k, v in payload.items():
            if "id" in k.lower() and v:
                return str(v)
    return None

def extract_cli_from_payload(payload):
    """Extracts the Service Name."""
    if isinstance(payload, dict):
        if "termination_name" in payload and payload["termination_name"]:
            return str(payload["termination_name"]).strip()
        
        for k in CLI_KEYS:
            if k in payload and payload[k]:
                return str(payload[k]).strip()
    return ""

def extract_message_from_payload(payload):
    if isinstance(payload, dict):
        for k in ("message", "msg", "text", "body", "content"):
            if k in payload and payload[k]:
                return str(payload[k])
    return ""

# ===================== SCANNER ENGINE =====================

class TerminationScanner:
    """
    The 'Hunter' module.
    Listens to the Public Feed on Port 2087 to find Hot Terminations.
    """
    def __init__(self):
        self.ws_url = "wss://ivasms.com:2087/socket.io/" 
        self.is_running = False
        
        # Categorization regex
        self.service_patterns = {
            "Facebook": r"facebook|fb\b",
            "WhatsApp": r"whatsapp",
            "Telegram": r"telegram",
            "Google": r"google|gmail|youtube",
            "Instagram": r"instagram|ig\b",
            "TikTok": r"tiktok",
            "Twitter": r"twitter|x\.com",
            "Amazon": r"amazon",
            "Microsoft": r"microsoft",
            "Uber": r"uber",
            "Netflix": r"netflix",
            "Apple": r"apple"
        }

    async def start(self):
        self.is_running = True
        log("📡 Scanner Started (Port 2087)", "INFO")

        while self.is_running and not state.shutdown_event.is_set():
            # Connection Params (EIO=4, transport=websocket)
            params = {'EIO': '4', 'transport': 'websocket'}
            url = f"{self.ws_url}?{urlencode(params)}"
            
            headers = config.NUMBERS_HEADERS.copy()
            headers["Host"] = "ivasms.com:2087"
            headers["Origin"] = "https://www.ivasms.com"
            
            # Use captured session if available
            if state.current_cookies:
                cookie_str = "; ".join([f"{k}={v}" for k,v in state.current_cookies.items()])
                headers["Cookie"] = cookie_str
            if getattr(state, "current_user_agent", None):
                headers["User-Agent"] = state.current_user_agent

            try:
                async with aiohttp.ClientSession() as client:
                    async with client.ws_connect(url, headers=headers, ssl=False, timeout=20) as ws:
                        # 1. Send Handshake
                        await ws.send_str("40") 
                        log("📡 Scanner Connected", "OK")
                        
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await self._handle_frame(msg.data)
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                log("📡 Scanner Disconnected", "WARN")
                                break

            except Exception as e:
                # If 403, Cloudflare might be blocking the scanner too
                if "403" in str(e):
                    log(f"📡 Scanner 403 Forbidden. Signaling Browser...", "WARN")
                    state.force_refresh_cookies = True
                
                await asyncio.sleep(5)

    async def _handle_frame(self, text: str):
        """
        Parses frames like: 42["send_message_test",{"termination_id":...}]
        """
        if text == "2": return # Ping

        if text.startswith("42"):
            try:
                data_arr = find_json_array_in_text(text)
                
                if data_arr and len(data_arr) > 1:
                    event_name = data_arr[0]
                    if event_name == "send_message_test":
                        await self._process_payload(data_arr[1])
                        
                elif data_arr and len(data_arr) > 0:
                    await self._process_payload(data_arr[0])
            except: 
                pass

    async def _process_payload(self, payload: dict):
        """
        Extracts ID and Name, updates Database.
        """
        # 1. Extract ID (Critical)
        term_id = extract_termid_from_payload(payload)
        if not term_id: return

        # 2. Extract Name & Message
        raw_name = extract_cli_from_payload(payload)   # e.g. "ZAMBIA 716"
        msg_text = extract_message_from_payload(payload)
        
        # 3. Categorize
        detected_service = "Other"
        combined_text = f"{raw_name} {msg_text}"
        
        for service, pattern in self.service_patterns.items():
            if re.search(pattern, combined_text, re.IGNORECASE):
                detected_service = service
                break
        
        # Display Name Logic
        display_name = raw_name if raw_name else "Unknown Range"

        # 4. Save to MongoDB
        # Using the new db module
        await db.db.record_scanner_hit(term_id, display_name, detected_service)
