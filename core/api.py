import aiohttp
import asyncio
import utils  # Merged State + Utils
import config
from utils import log
import re
import time

async def get_headers_and_cookies():
    """
    Constructs headers strictly from the Browser's captured state.
    No hardcoded headers are used.
    """
    headers = {}
    
    # 1. User-Agent from Browser
    if getattr(utils, "current_user_agent", None):
        headers["User-Agent"] = utils.current_user_agent
        
    # 2. Cookies from Browser
    cookies = utils.current_cookies
    if cookies:
        cookie_string = "; ".join([f"{k}={v}" for k,v in cookies.items()])
        headers["Cookie"] = cookie_string
        
    # 3. Standard headers usually required (can be kept minimal)
    headers["Accept"] = "*/*"
    headers["Connection"] = "keep-alive"
        
    return headers, cookies

async def get_ws_creds_by_request():
    """Fetch WebSocket token/user via HTTP request."""
    url = config.LIVE_SMS_URL
    headers, cookies = await get_headers_and_cookies()
    
    try:
        async with aiohttp.ClientSession(cookies=cookies) as session:
            async with session.get(url, headers=headers, timeout=15) as resp:
                if resp.status in [403, 503, 401]:
                    log("🛡️ WS Cred Fetch Blocked (401/403). Triggering Browser...", "WARN")
                    utils.force_refresh_cookies = True
                    return False

                html = await resp.text()
                m = re.search(
                    r"io\.connect\('https://ivasms\.com:2087/livesms',\s*\{\s*query\s*:\s*\{\s*token:\s*'([^']+)'[^}]*user:\"([^\"}]+)\"", 
                    html, 
                    re.DOTALL
                )
                
                if m:
                    utils.current_livesms_token = m.group(1).strip()
                    utils.current_livesms_user = m.group(2).strip()
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
                        utils.force_refresh_cookies = True
                    return False, f"HTTP Error {resp.status}"
                
                text = await resp.text()
                
                # Regex to find Termination Ranges
                pattern = r"show_numbers\('(\d+)'\)[^>]*>([^<]+)<"
                matches = re.findall(pattern, text)
                
                new_data = {}
                for term_id, name in matches:
                    name = name.strip()
                    if name not in new_data:
                        new_data[name] = []
                    # Store range placeholder
                    new_data[name].append({'id': term_id, 'number': 'Range ' + term_id, 'country_iso': '??'})

                utils.numbers_data = new_data
                return True, f"Fetched {len(new_data)} ranges."

    except Exception as e:
        return False, str(e)

async def add_number(term_id):
    """Buy/Add a number."""
    url = config.ADD_NUMBER_URL
    headers, cookies = await get_headers_and_cookies()
    
    data = {
        "termination_id": term_id,
        "amount": "1",
        "_token": utils.current_csrf_token
    }
    
    try:
        async with aiohttp.ClientSession(cookies=cookies) as session:
            async with session.post(url, headers=headers, data=data) as resp:
                t = await resp.text()
                if resp.status == 200:
                    return True, "Number added successfully."
                elif resp.status == 403:
                    utils.force_refresh_cookies = True
                    return False, "Session expired (403). Retrying..."
                return False, f"Failed: {t[:100]}"
    except Exception as e:
        return False, str(e)

async def remove_range(range_name):
    """Deletes all numbers in a named range."""
    items = utils.numbers_data.get(range_name, [])
    if not items:
        return False, "Range not found in memory."
        
    ids = [item['id'] for item in items if 'id' in item]
    if not ids:
        return False, "No IDs found."

    url = config.REMOVE_NUMBER_URL
    headers, cookies = await get_headers_and_cookies()
    
    CHUNK_SIZE = 100
    total_removed = 0
    
    try:
        async with aiohttp.ClientSession(cookies=cookies) as session:
            for i in range(0, len(ids), CHUNK_SIZE):
                chunk_ids = ids[i:i + CHUNK_SIZE]
                data = aiohttp.FormData()
                data.add_field("_token", utils.current_csrf_token)
                for num_id in chunk_ids:
                    data.add_field("NumberID[]", num_id)

                async with session.post(url, headers=headers, data=data) as resp:
                    if resp.status == 200:
                        total_removed += len(chunk_ids)
                        log(f"Removed chunk {i}-{i+len(chunk_ids)}", "INFO")
                        await asyncio.sleep(0.5)
                    else:
                        return False, f"HTTP {resp.status}"
            
            if range_name in utils.numbers_data:
                del utils.numbers_data[range_name]
                
            return True, f"Removed {total_removed} numbers."

    except Exception as e:
        return False, str(e)
