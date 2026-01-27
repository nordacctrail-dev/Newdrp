import socketio
import asyncio
import ssl
import state
import config
from urllib.parse import urlencode # Added for safe query string building
from utils import log, extract_otp
from core.notifier import send_otp_notification

# Initialize Socket.IO Client
# ssl_verify=False is crucial for custom ports like 2087
sio = socketio.AsyncClient(logger=True, engineio_logger=True, ssl_verify=False)

@sio.event
async def connect():
    log("🔌 WebSocket Connected!", "OK")
    await sio.emit("40/livesms,")

@sio.event
async def connect_error(data):
    log(f"WebSocket Connection Error: {data}", "ERROR")

@sio.event
async def disconnect():
    log("🔌 WebSocket Disconnected", "WARN")

@sio.on('*')
async def catch_all(event, data):
    payload = None
    if isinstance(data, dict):
        payload = data
    elif isinstance(data, list) and len(data) > 0:
        payload = data[1] if len(data) > 1 else data[0]

    if payload and isinstance(payload, dict):
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

            await send_otp_notification(otp_data)
            log(f"🔥 OTP: {otp_code} | {otp_data['originator']}", "OK")

async def websocket_loop():
    """
    Main loop to keep WebSocket alive.
    """
    while not state.shutdown_event.is_set():
        if not state.current_livesms_token:
            await asyncio.sleep(5)
            continue

        try:
            if not sio.connected:
                log(f"🔍 DEBUG: Preparing WS Connection...", "INFO")
                
                # 1. Prepare Query Params (Token & User)
                # The server expects these in the URL: .../?token=X&user=Y
                params = {
                    'token': state.current_livesms_token,
                    'user': state.current_livesms_user
                }
                query_string = urlencode(params)
                
                # 2. Construct Full URL
                # python-socketio takes the base URL and appends /socket.io/ automatically
                # We append the query string to the base URL.
                base_host = "https://ivasms.com:2087" 
                connection_url = f"{base_host}?{query_string}"
                
                log(f"🔗 Connecting to: {base_host} with params", "INFO")

                # 3. Headers
                headers = {
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Origin": "https://www.ivasms.com",
                    "Host": "ivasms.com:2087",
                }
                
                # Add Cookies (Important!)
                if state.current_cookies:
                    cookie_string = "; ".join([f"{k}={v}" for k,v in state.current_cookies.items()])
                    headers["Cookie"] = cookie_string

                # 4. CONNECT
                await sio.connect(
                    connection_url, 
                    socketio_path='socket.io',
                    transports=['websocket'],
                    headers=headers
                    # Note: We removed 'auth={...}' because we are passing creds in the URL now
                )
                
            await sio.wait()
            
        except Exception as e:
            log(f"WS Loop Exception: {e}", "ERROR")
            await asyncio.sleep(10)
