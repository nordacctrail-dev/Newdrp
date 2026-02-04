import aiohttp
import asyncio
import utils  # CHANGED
import config
from utils import log
import re
import time

async def get_headers_and_cookies():
    """Helper to construct headers with fresh cookies."""
    headers = config.NUMBERS_HEADERS.copy()
    cookies = utils.current_cookies # CHANGED: utils
    
    if cookies:
        cookie_string = "; ".join([f"{k}={v}" for k,v in cookies.items()])
        headers["Cookie"] = cookie_string
        
    return headers, cookies

async def get_ws_creds_by_request():
    """
    Fetch WebSocket token/user via HTTP request.
    """
    url = config.LIVE_SMS_URL
    headers, cookies = await get_headers_and_cookies()
    
    try:
        async with aiohttp.ClientSession(cookies=cookies) as session:
            async with session.get(url, headers=headers, timeout=15) as resp:
                if resp.status in [403, 503, 401]:
                    log("🛡️ WS Cred Fetch Blocked (401). Triggering Browser Solver...", "WARN")
                    utils.force_refresh_cookies = True # CHANGED: utils
                    return False

                html = await resp.text()
                m = re.search(
                    r"io\.connect\('https://ivasms\.com:2087/livesms',\s*\{\s*query\s*:\s*\{\s*token:\s*'([^']+)'[^}]*user:\"([^\"}]+)\"", 
                    html, 
                    re.DOTALL
                )
                
                if m:
                    utils.current_livesms_token = m.group(1).strip() # CHANGED
                    utils.current_livesms_user = m.group(2).strip() # CHANGED
                    return True
    except Exception as e:
        log(f"WS Creds Fetch Error: {e}", "ERROR")
    return False

async def fetch_numbers():
    """Fetch active numbers from the portal."""
    url = config.NUMBERS_BASE_URL
    headers, cookies = await get_headers_and_cookies()
    
    try:
        async with aiohttp.ClientSession(cookies=cookies) as session:
            async with session.get(url, headers=headers, timeout=20) as resp:
                if resp.status != 200:
                    if resp.status == 403:
                        utils.force_refresh_cookies = True # CHANGED
                    return False, f"HTTP Error {resp.status}"
                
                text = await resp.text()
                
                # Regex to find Termination Ranges and their IDs
                # Look for patterns like: show_numbers('123456') ... >RANGE NAME<
                # This is a heuristic; might need adjustment based on actual HTML
                pattern = r"show_numbers\('(\d+)'\)[^>]*>([^<]+)<"
                matches = re.findall(pattern, text)
                
                new_data = {}
                count = 0
                
                for term_id, name in matches:
                    name = name.strip()
                    # We might need a separate call to get the actual numbers inside this range
                    # For now, we store the range ID.
                    if name not in new_data:
                        new_data[name] = []
                    
                    # Store a dummy object representing the range (since we might not have the numbers yet)
                    # OR if the page actually lists numbers, we parse them.
                    # Assuming the page lists ranges:
                    new_data[name].append({'id': term_id, 'number': 'Range ' + term_id, 'country_iso': '??'})
                    count += 1

                utils.numbers_data = new_data # CHANGED
                utils.numbers_last_update = time.time() # CHANGED
                return True, f"Fetched {len(new_data)} ranges."

    except Exception as e:
        return False, str(e)

async def add_number(term_id):
    """Buy/Add a number/range."""
    url = config.ADD_NUMBER_URL
    headers, cookies = await get_headers_and_cookies()
    
    data = {
        "termination_id": term_id,
        "amount": "1",
        "_token": utils.current_csrf_token # CHANGED
    }
    
    try:
        async with aiohttp.ClientSession(cookies=cookies) as session:
            async with session.post(url, headers=headers, data=data) as resp:
                t = await resp.text()
                if resp.status == 200:
                    return True, "Number added successfully."
                elif resp.status == 403:
                    utils.force_refresh_cookies = True # CHANGED
                    return False, "Session expired (403). Retrying..."
                return False, f"Failed: {t[:100]}"
    except Exception as e:
        return False, str(e)

async def remove_range(range_name):
    """Deletes all numbers in a named range."""
    # 1. Get IDs from local cache
    items = utils.numbers_data.get(range_name, []) # CHANGED
    if not items:
        return False, "Range not found in memory. Refresh first."
        
    ids = [item['id'] for item in items if 'id' in item]
    if not ids:
        return False, "No IDs found in range."

    url = config.REMOVE_NUMBER_URL
    headers, cookies = await get_headers_and_cookies()
    
    # Send chunks
    CHUNK_SIZE = 100
    total_removed = 0
    
    try:
        async with aiohttp.ClientSession(cookies=cookies) as session:
            for i in range(0, len(ids), CHUNK_SIZE):
                chunk_ids = ids[i:i + CHUNK_SIZE]
                
                data = aiohttp.FormData()
                data.add_field("_token", utils.current_csrf_token) # CHANGED
                for num_id in chunk_ids:
                    data.add_field("NumberID[]", num_id)

                async with session.post(url, headers=headers, data=data) as resp:
                    if resp.status == 200:
                        total_removed += len(chunk_ids)
                        log(f"Removed chunk {i}-{i+len(chunk_ids)}", "INFO")
                        await asyncio.sleep(0.5)
                    else:
                        return False, f"HTTP {resp.status}"
            
            # Clear from memory
            if range_name in utils.numbers_data: # CHANGED
                del utils.numbers_data[range_name] # CHANGED
                
            return True, f"Removed {total_removed} numbers."

    except Exception as e:
        return False, str(e)
