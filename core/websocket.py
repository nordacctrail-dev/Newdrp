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
    log("伯 WebSocket Connected (/livesms)!", "OK")

@sio.event(namespace='/livesms')
async def connect_error(data):
    log(f"WebSocket Connection Error (/livesms): {data}", "ERROR")

@sio.event(namespace='/livesms')
async def disconnect():
    log("伯 WebSocket Disconnected (/livesms)", "WARN")

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
        log(f"櫨 OTP: {otp_code} | {otp_data['originator']}", "OK")

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
                log(f"剥 DEBUG: Preparing WS Connection...", "INFO")
                
                params = {
                    'token': state.current_livesms_token,
                    'user': state.current_livesms_user
                }
                
                # Construct URL
                base_host = "https://ivasms.com:2087"
                query_string = urlencode(params)
                connection_url = f"{base_host}?{query_string}"

                # DYNAMIC HEADERS (The Fix)
                # We use the UA captured from the browser
                headers = {
                    "User-Agent": state.current_user_agent,
                    "Origin": "https://www.ivasms.com",
                    "Host": "ivasms.com:2087",
                }
                
                if state.current_cookies:
                    cookie_string = "; ".join([f"{k}={v}" for k,v in state.current_cookies.items()])
                    headers["Cookie"] = cookie_string

                log(f"迫 Connecting with UA: {state.current_user_agent[:30]}...", "INFO")

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
            # --- CRITICAL FIX: Trigger Cloudflare Solve on WS 403 ---
            if "401" in err_str or "403" in err_str or "handshake" in err_str or "rejected" in err_str:
                log(f"🚨 WS Handshake 403/Rejected: {e}", "WARN")
                log("🔄 Triggering Browser Cloudflare Solver...", "WARN")
                
                # 1. Signal the browser to go solve Cloudflare
                state.force_refresh_cookies = True
                
                # 2. Clear token so the browser re-scrapes it AFTER solving
                state.current_livesms_token = None
            else:
                log(f"WS Loop Exception: {e}", "ERROR")
            
            # Wait a bit to let the browser do its job
            await asyncio.sleep(15)
