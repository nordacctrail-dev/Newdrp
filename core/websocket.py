import socketio
import asyncio
import state
import config
from utils import log, extract_otp
from core.notifier import send_otp_notification

# Async Socket.IO Client
sio = socketio.AsyncClient(logger=False, engineio_logger=False)

@sio.event
async def connect():
    log("🔌 WebSocket Connected!", "OK")
    # Send handshake message specific to IVASMS
    await sio.emit("40/livesms,")

@sio.event
async def connect_error(data):
    log(f"WebSocket Connection Error: {data}", "ERROR")

@sio.event
async def disconnect():
    log("🔌 WebSocket Disconnected", "WARN")

# Handle raw messages (IVASMS uses raw JSON arrays often)
@sio.on('*')
async def catch_all(event, data):
    # Depending on IVASMS version, data might be directly in event or data
    # We inspect the payload
    payload = None
    if isinstance(data, dict):
        payload = data
    elif isinstance(data, list) and len(data) > 0:
        payload = data[1] if len(data) > 1 else data[0]

    if payload and isinstance(payload, dict):
        # Check if it's an SMS
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
            
            # Store in History
            state.otp_history.append(otp_data)
            if len(state.otp_history) > state.MAX_HISTORY_SIZE:
                state.otp_history.pop(0)
            
            # Update Stats
            state.otp_stats["total"] += 1

            # Notify Telegram
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
                # Construct URL with auth query params
                # IVASMS requires token & user in the query string
                token = state.current_livesms_token
                user = state.current_livesms_user
                
                # We use the extra headers to pass cookies
                cookies = state.current_cookies
                
                # Connect
                base = config.WS_BASE.replace("wss://", "https://").replace("/socket.io/", "")
                await sio.connect(
                    base, 
                    socketio_path='socket.io',
                    transports=['websocket'],
                    headers={'Cookie': "; ".join([f"{k}={v}" for k,v in cookies.items()])},
                    auth={'token': token, 'user': user} # Some versions use auth dict
                )
                
                # If query params are strictly required in URL (often true for socket.io v4)
                # python-socketio handles this if passed in 'auth' or we might need a custom URL
                # This setup is standard for modern Socket.IO
                
            await sio.wait()
            
        except Exception as e:
            log(f"WS Loop Exception: {e}", "ERROR")
            await asyncio.sleep(10) # Backoff
