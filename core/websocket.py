import socketio
import asyncio
import state
import config
from urllib.parse import urlencode
from utils import log, extract_otp
from core.notifier import send_otp_notification
import core.api as api

# Initialize Client
sio = socketio.AsyncClient(logger=True, engineio_logger=True, ssl_verify=False)

@sio.event(namespace='/livesms')
async def connect():
    log("✅ WebSocket Connected (/livesms)!", "OK")

@sio.event(namespace='/livesms')
async def connect_error(data):
    log(f"WebSocket Connection Error (/livesms): {data}", "ERROR")

@sio.event(namespace='/livesms')
async def disconnect():
    log("⚠️ WebSocket Disconnected (/livesms)", "WARN")

@sio.on('*', namespace='/livesms')
async def catch_all(event, data):
    payload = None
    if isinstance(data, dict):
        payload = data
    elif isinstance(data, list) and len(data) > 0:
        if isinstance(data[0], dict):
            payload = data[0]
        elif len(data) > 1 and isinstance(data[1], dict):
            payload = data[1]

    if payload and isinstance(payload, dict):
        process_payload(payload)

def process_payload(payload):
    msg_text = payload.get("message", "")
    if msg_text:
        otp_code = extract_otp(msg_text)
        
        otp_data = {
            "originator": payload.get("originator", "Unknown"),
            "recipient": payload.get("recipient", "Unknown"),
            "otp_code": otp_code,
            "message": msg_text,
            "country": payload.get("country_iso", "Unknown"),
        }
        
        state.otp_history.append(otp_data)
        if len(state.otp_history) > state.MAX_HISTORY_SIZE:
            state.otp_history.pop(0)
        
        state.otp_stats["total"] += 1
        asyncio.create_task(send_otp_notification(otp_data))
        log(f"📩 OTP: {otp_code} | {otp_data['originator']}", "OK")

async def websocket_loop():
    """Main loop."""
    while not state.shutdown_event.is_set():
        # Wait for token AND user agent
        await api.get_ws_creds_by_request()
        if not state.current_livesms_token or not getattr(state, "current_user_agent", None):
            wait_time = 10 if state.force_refresh_cookies else 5
            await asyncio.sleep(wait_time)
            continue

        try:
            if not sio.connected:
                log(f"🔌 DEBUG: Preparing WS Connection...", "INFO")
                
                params = {
                    'token': state.current_livesms_token,
                    'user': state.current_livesms_user
                }
                
                # Construct URL
                base_host = "https://ivasms.com:2087"
                query_string = urlencode(params)
                connection_url = f"{base_host}?{query_string}"

                # DYNAMIC HEADERS
                headers = {
                    "User-Agent": state.current_user_agent,
                    "Origin": "https://www.ivasms.com",
                    "Host": "ivasms.com:2087",
                }
                
                if state.current_cookies:
                    cookie_string = "; ".join([f"{k}={v}" for k,v in state.current_cookies.items()])
                    headers["Cookie"] = cookie_string

                log(f"🔄 Connecting with UA: {state.current_user_agent[:30]}...", "INFO")

                await sio.connect(
                    connection_url, 
                    namespaces=['/livesms'],
                    transports=['websocket'],
                    socketio_path='socket.io',
                    headers=headers
                )
                
            await sio.wait()
            
        except Exception as e:
            err_str = str(e).lower()
            if "401" in err_str or "403" in err_str or "handshake" in err_str or "rejected" in err_str:
                log(f"🚨 WS Handshake 403/Rejected: {e}", "WARN")
                log("🔄 Triggering Browser Cloudflare Solver...", "WARN")
                
                state.force_refresh_cookies = True
                state.current_livesms_token = None
            else:
                log(f"WS Loop Exception: {e}", "ERROR")
            
            await asyncio.sleep(15)

# --- NEW WATCHDOG FUNCTION ---
async def credential_watchdog():
    """
    Proactively checks credentials every 15 seconds.
    If blocked (403), api.get_ws_creds_by_request automatically triggers the browser solver.
    """
    log("🛡️ Credential Watchdog Started", "INFO")
    while not state.shutdown_event.is_set():
        try:
            # Don't check if we are already in the middle of solving
            if not state.force_refresh_cookies:
                # This function returns True if success, False if blocked/failed
                # Crucially: It internally sets state.force_refresh_cookies = True on 403
                await api.get_ws_creds_by_request()
            
            # Check every 15 seconds (adjust if needed, but don't go too low or you risk bans)
            await asyncio.sleep(15) 
        except Exception as e:
            log(f"Watchdog Error: {e}", "ERROR")
            await asyncio.sleep(15)
