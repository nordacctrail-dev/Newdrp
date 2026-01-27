import socketio
import asyncio
import state
import config
from utils import log, extract_otp
from core.notifier import send_otp_notification

# --- ENABLE DEBUG LOGGING ---
# Set logger=True and engineio_logger=True to see the raw handshake
sio = socketio.AsyncClient(logger=True, engineio_logger=True)

@sio.event
async def connect():
    log("🔌 WebSocket Connected!", "OK")
    # Send handshake message specific to IVASMS
    await sio.emit("40/livesms,")

@sio.event
async def connect_error(data):
    # Log the full error data to see if it's a 403, 401, or 400
    log(f"WebSocket Connection Error: {data}", "ERROR")

@sio.event
async def disconnect():
    log("🔌 WebSocket Disconnected", "WARN")

# Handle raw messages (IVASMS uses raw JSON arrays often)
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
                # DEBUG: Log the credentials we are about to use
                log(f"🔍 DEBUG: Connecting with User: {state.current_livesms_user}", "INFO")
                log(f"🔍 DEBUG: Connecting with Token: {state.current_livesms_token[:10]}...", "INFO")
                
                # Construct URL
                base = config.WS_BASE.replace("wss://", "https://").replace("/socket.io/", "")
                
                # We commented out cookie fetching in browser.py to fix the crash.
                # If cookies are empty, this might be why WS fails.
                # Let's check if we have cookies.
                if not state.current_cookies:
                    log("⚠️ DEBUG: No cookies found in state! WS might fail.", "WARN")
                
                # Connect
                await sio.connect(
                    base, 
                    socketio_path='socket.io',
                    transports=['websocket'],
                    # Pass empty dict if cookies are None to avoid errors
                    headers={'Cookie': "; ".join([f"{k}={v}" for k,v in state.current_cookies.items()])} if state.current_cookies else {},
                    auth={'token': state.current_livesms_token, 'user': state.current_livesms_user}
                )
                
            await sio.wait()
            
        except Exception as e:
            # Print full exception traceback for clarity
            import traceback
            log(f"WS Loop Exception: {e}", "ERROR")
            traceback.print_exc()
            await asyncio.sleep(10) # Backoff
