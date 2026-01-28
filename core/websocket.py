import socketio
import asyncio
import state
import config
from urllib.parse import urlencode
from utils import log, extract_otp
from core.notifier import send_otp_notification

# Initialize Socket.IO Client (Async)
# ssl_verify=False to bypass certificate issues on custom port 2087
sio = socketio.AsyncClient(logger=True, engineio_logger=True, ssl_verify=False)

# --- EVENT HANDLERS FOR /livesms NAMESPACE ---

@sio.event(namespace='/livesms')
async def connect():
    log("🔌 WebSocket Connected (/livesms)!", "OK")

@sio.event(namespace='/livesms')
async def connect_error(data):
    log(f"WebSocket Connection Error (/livesms): {data}", "ERROR")

@sio.event(namespace='/livesms')
async def disconnect():
    log("🔌 WebSocket Disconnected (/livesms)", "WARN")

@sio.on('*', namespace='/livesms')
async def catch_all(event, data):
    """Handles incoming messages on the /livesms namespace."""
    # Logic to parse [event, payload] or just payload
    payload = None
    
    # ivasms usually sends a list: [data_dict] or [event_name, data_dict]
    if isinstance(data, dict):
        payload = data
    elif isinstance(data, list) and len(data) > 0:
        # If the first item is a dict, that's it. 
        # If first item is string (event name) and second is dict, take second.
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

        # Use create_task to run async notification from sync callback if needed,
        # but here we are in async context usually.
        asyncio.create_task(send_otp_notification(otp_data))
        log(f"🔥 OTP: {otp_code} | {otp_data['originator']}", "OK")

async def websocket_loop():
    """Main loop to keep WebSocket alive."""
    while not state.shutdown_event.is_set():
        if not state.current_livesms_token:
            await asyncio.sleep(5)
            continue

        try:
            if not sio.connected:
                log(f"🔍 DEBUG: Preparing WS Connection...", "INFO")
                
                # 1. Build Query Params
                params = {
                    'token': state.current_livesms_token,
                    'user': state.current_livesms_user
                }
                
                # 2. Build Connection URL
                # python-socketio expects the base URL. It adds /socket.io/ itself.
                # BUT we need to pass the query string to the base URL so it gets appended.
                base_host = "https://ivasms.com:2087"
                query_string = urlencode(params)
                connection_url = f"{base_host}?{query_string}"

                # 3. Headers (Mimicking t3s.py)
                headers = {
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Origin": "https://www.ivasms.com",
                    "Host": "ivasms.com:2087",
                }
                
                if state.current_cookies:
                    cookie_string = "; ".join([f"{k}={v}" for k,v in state.current_cookies.items()])
                    headers["Cookie"] = cookie_string

                log(f"🔗 Connecting to: {base_host} ...", "INFO")

                # 4. Connect with Namespaces
                # This performs the handshake AND the /livesms connection packet
                await sio.connect(
                    connection_url, 
                    namespaces=['/livesms'],
                    transports=['websocket'],
                    socketio_path='socket.io',
                    headers=headers
                )
                
            await sio.wait()
            
        except Exception as e:
            # Check for Cloudflare-like errors
            err_str = str(e).lower()
            if "403" in err_str or "handshake" in err_str:
                log(f"WS Handshake 403: {e}", "WARN")
                # Trigger a browser refresh if possible by clearing token
                state.current_livesms_token = None
            else:
                log(f"WS Loop Exception: {e}", "ERROR")
            
            await asyncio.sleep(10)
