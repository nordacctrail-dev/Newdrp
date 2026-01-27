import socketio
import asyncio
import ssl
import state
import config
from utils import log, extract_otp
from core.notifier import send_otp_notification

# Initialize Async Client with SSL verification disabled
# We create a custom SSL context that ignores certificate errors
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Initialize Socket.IO Client
# 'ssl' argument is not directly supported in AsyncClient init, 
# so we handle it via the connector or simply rely on loose headers first.
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
                log(f"🔍 DEBUG: Connecting with User: {state.current_livesms_user}", "INFO")
                
                # Construct URL
                base = config.WS_BASE.replace("wss://", "https://").replace("/socket.io/", "")
                
                # 1. PREPARE HEADERS (Crucial for bypassing blocks)
                # We must mimic the browser exactly
                headers = {
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Origin": "https://www.ivasms.com",
                    "Host": "ivasms.com:2087",
                    "Accept-Language": "en-US,en;q=0.9",
                }
                
                # Add Cookies
                if state.current_cookies:
                    cookie_string = "; ".join([f"{k}={v}" for k,v in state.current_cookies.items()])
                    headers["Cookie"] = cookie_string
                else:
                    log("⚠️ DEBUG: No cookies found! WS will likely fail.", "WARN")

                # 2. CONNECT
                await sio.connect(
                    base, 
                    socketio_path='socket.io',
                    transports=['websocket'],
                    headers=headers,
                    auth={'token': state.current_livesms_token, 'user': state.current_livesms_user}
                )
                
            await sio.wait()
            
        except Exception as e:
            # Only log the error message to keep logs clean, or use e for debug
            log(f"WS Loop Exception: {e}", "ERROR")
            await asyncio.sleep(10) # Backoff
