import socketio
import asyncio
import utils  # CHANGED
import config
from urllib.parse import urlencode
from utils import log, extract_otp
from core.notifier import send_otp_notification
import core.api as api

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
        
        utils.otp_history.append(otp_data) # CHANGED
        if len(utils.otp_history) > utils.MAX_HISTORY_SIZE: # CHANGED
            utils.otp_history.pop(0) # CHANGED
        
        utils.otp_stats["total"] += 1 # CHANGED
        asyncio.create_task(send_otp_notification(otp_data))
        log(f"📩 OTP: {otp_code} | {otp_data['originator']}", "OK")

async def websocket_loop():
    """Main loop."""
    while not utils.shutdown_event.is_set(): # CHANGED
        await api.get_ws_creds_by_request()
        if not utils.current_livesms_token or not getattr(utils, "current_user_agent", None): # CHANGED
            wait_time = 10 if utils.force_refresh_cookies else 5 # CHANGED
            await asyncio.sleep(wait_time)
            continue

        try:
            if not sio.connected:
                log(f"🔌 DEBUG: Preparing WS Connection...", "INFO")
                
                params = {
                    'token': utils.current_livesms_token, # CHANGED
                    'user': utils.current_livesms_user # CHANGED
                }
                
                base_host = "https://ivasms.com:2087"
                query_string = urlencode(params)
                connection_url = f"{base_host}?{query_string}"

                headers = {
                    "User-Agent": utils.current_user_agent, # CHANGED
                    "Origin": "https://www.ivasms.com",
                    "Host": "ivasms.com:2087",
                }
                
                if utils.current_cookies: # CHANGED
                    cookie_string = "; ".join([f"{k}={v}" for k,v in utils.current_cookies.items()]) # CHANGED
                    headers["Cookie"] = cookie_string

                log(f"🔄 Connecting with UA: {utils.current_user_agent[:30]}...", "INFO") # CHANGED

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
                
                utils.force_refresh_cookies = True # CHANGED
                utils.current_livesms_token = None # CHANGED
            else:
                log(f"WS Loop Exception: {e}", "ERROR")
            
            await asyncio.sleep(15)

async def credential_watchdog():
    log("🛡️ Credential Watchdog Started", "INFO")
    while not utils.shutdown_event.is_set(): # CHANGED
        try:
            if not utils.force_refresh_cookies: # CHANGED
                await api.get_ws_creds_by_request()
            await asyncio.sleep(15) 
        except Exception as e:
            log(f"Watchdog Error: {e}", "ERROR")
            await asyncio.sleep(15)
