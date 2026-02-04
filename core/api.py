import aiohttp
import asyncio
import utils
import config
from utils import log
import re
import time

async def get_ws_creds_by_request():
    """
    Fetch WebSocket token/user via HTTP request using captured cookies.
    Triggers Cloudflare solving if a 403 is encountered.
    """
    url = config.LIVE_SMS_URL
    headers, cookies = await get_headers_and_cookies()
    
    try:
        async with aiohttp.ClientSession(cookies=cookies) as session:
            async with session.get(url, headers=headers, timeout=15) as resp:
                # Detection: If blocked, signal the browser to solve
                if resp.status in [403, 503, 401]:
                    log("🛡️ WS Cred Fetch Blocked (401). Triggering Browser Solver...", "WARN")
                    state.force_refresh_cookies = True
                    return False

                html = await resp.text()
                # Same regex logic moved to request-based HTML
                m = re.search(
                    r"io\.connect\('https://ivasms\.com:2087/livesms',\s*\{\s*query\s*:\s*\{\s*token:\s*'([^']+)'[^}]*user:\"([^\"}]+)\"", 
                    html, 
                    re.DOTALL
                )
                
                if m:
                    state.current_livesms_token = m.group(1).strip()
                    state.current_livesms_user = m.group(2).strip()
                    return True
    except Exception as e:
        log(f"WS Cred Request Failed: {e}", "ERROR")
    return False

async def get_headers_and_cookies():
    """
    Constructs headers and cookies using the LIVE browser state.
    """
    cookies = state.current_cookies.copy()
    headers = config.NUMBERS_HEADERS.copy()
    
    if getattr(state, "current_user_agent", None):
        headers["User-Agent"] = state.current_user_agent
    else:
        log("⚠️ API Warning: Browser User-Agent not captured yet.", "WARN")

    if state.current_csrf_token:
        headers["X-CSRF-TOKEN"] = state.current_csrf_token
        
    return headers, cookies

async def fetch_numbers():
    """
    Refreshes the list of numbers.
    Includes RETRY logic for Cloudflare 403s.
    """
    url = config.NUMBERS_BASE_URL
    
    # Retry loop (Try once, if 403, wait for browser, then try again)
    for attempt in range(2):
        headers, cookies = await get_headers_and_cookies()
        
        BATCH_SIZE = 100  # Match t3s.py (safe size)
        start = 0
        draw = 1
        all_rows = []
        is_403 = False
        
        log(f"🔄 Fetching numbers (Attempt {attempt+1})...", "INFO")
        
        try:
            async with aiohttp.ClientSession(cookies=cookies) as session:
                while True:
                    # Exact params to mimic DataTables behavior
                    params = {
                        "draw": str(draw),
                        "columns[0][data]": "number_id",
                        "columns[0][name]": "id",
                        "columns[0][orderable]": "false",
                        "columns[1][data]": "Number",
                        "columns[2][data]": "range",
                        "columns[3][data]": "A2P",
                        "columns[13][data]": "action",
                        "order[0][column]": "2",
                        "order[0][dir]": "desc",
                        "start": str(start),
                        "length": str(BATCH_SIZE),
                        "search[value]": ""
                    }
                    
                    async with session.get(url, headers=headers, params=params) as resp:
                        # --- CLOUDFLARE DETECTION & RECOVERY ---
                        if resp.status == 403 or resp.status == 503 or resp.status == 401:
                            if attempt == 0:
                                log("⚠️ API hit 401/403/503 - Triggering Browser Refresh...", "WARN")
                                state.force_refresh_cookies = True
                                
                                # Wait for browser to do its job (up to 20s)
                                for _ in range(10):
                                    if not state.force_refresh_cookies:
                                        log("✅ Browser finished refresh. Retrying API...", "OK")
                                        break
                                    await asyncio.sleep(2)
                                
                                is_403 = True
                                break # Break inner while loop to restart outer attempt loop
                            else:
                                return False, "❌ Cloudflare Loop (Browser failed to solve)"

                        if resp.status != 200:
                            return False, f"HTTP {resp.status} (Possible Cloudflare Block)"

                        data = await resp.json()
                        rows = data.get("data", [])
                        
                        # Determine Total Records
                        total_records = data.get("recordsTotal") or data.get("recordsFiltered") or 0
                        try:
                            total_records = int(total_records)
                        except:
                            total_records = 0
                        
                        if not rows:
                            break
                            
                        all_rows.extend(rows)
                        
                        # Stop if we fetched everything
                        if len(all_rows) >= total_records:
                            break
                            
                        # Stop if server returned fewer items than requested (last page)
                        if len(rows) < BATCH_SIZE:
                            break
                            
                        # Next Page
                        start += BATCH_SIZE
                        draw += 1
                        await asyncio.sleep(0.2) 
                
                if is_403:
                    continue # Restart the attempt loop

                # --- PROCESS ALL ROWS ---
                groups = {}
                for row in all_rows:
                    # 1. Get Phone Number
                    phone_number = row.get("Number")
                    if not phone_number: continue
                    phone_number = str(phone_number).strip()

                    # 2. Get Range Name
                    rng = row.get("range", "Unknown")
                    
                    # 3. Extract ID
                    num_id_html = row.get("number_id", "")
                    num_id_match = re.search(r'value="(\d+)"', num_id_html)
                    
                    if num_id_match:
                        num_id = num_id_match.group(1)
                        
                        if rng not in groups: 
                            groups[rng] = []
                        
                        groups[rng].append({
                            "number": phone_number,
                            "id": num_id
                        })

                state.numbers_data = groups 
                state.numbers_last_update = time.time()
                
                total = sum(len(items) for items in groups.values())
                return True, f"Fetched {total} numbers in {len(groups)} ranges."

        except Exception as e:
            return False, str(e)
            
    return False, "Failed after retries"

async def add_number(term_id: str):
    """Adds a number by Termination ID."""
    if not state.current_csrf_token:
        return False, "❌ Missing CSRF Token (Wait for browser login)"

    url = config.ADD_NUMBER_URL
    headers, cookies = await get_headers_and_cookies()
    data = {"_token": state.current_csrf_token, "id": str(term_id)}

    try:
        async with aiohttp.ClientSession(cookies=cookies) as session:
            async with session.post(url, headers=headers, data=data) as resp:
                text = await resp.text()
                
                if resp.status == 200:
                    return True, "✅ Number Added Successfully"
                elif resp.status in [403, 401, 419]:
                    # Trigger refresh for next time, but fail this request
                    state.force_refresh_cookies = True
                    return False, "⛔ 403/401/419 - Session Expired (Browser refreshing... try again)"
                else:
                    return False, f"⚠️ Error {resp.status}: {text[:100]}"
    except Exception as e:
        return False, f"💥 Request Failed: {str(e)}"

async def remove_range(range_name: str):
    """Removes all numbers in a specific range."""
    if not hasattr(state, "numbers_data") or range_name not in state.numbers_data:
        return False, "❌ Range not found. Please refresh numbers first."

    # Extract IDs
    items = state.numbers_data[range_name]
    ids = [item['id'] for item in items]
    
    if not ids:
        return False, "⚠️ No numbers found in this range."

    url = config.REMOVE_NUMBER_URL
    headers, cookies = await get_headers_and_cookies()
    
    # Send chunks if too many numbers to avoid 413 Payload Too Large
    CHUNK_SIZE = 100
    total_removed = 0
    
    try:
        async with aiohttp.ClientSession(cookies=cookies) as session:
            # Loop through chunks
            for i in range(0, len(ids), CHUNK_SIZE):
                chunk_ids = ids[i:i + CHUNK_SIZE]
                
                data = aiohttp.FormData()
                data.add_field("_token", state.current_csrf_token)
                for num_id in chunk_ids:
                    data.add_field("NumberID[]", num_id)

                async with session.post(url, headers=headers, data=data) as resp:
                    text = await resp.text()
                    if resp.status == 200:
                        total_removed += len(chunk_ids)
                        log(f"Removed chunk {i}-{i+len(chunk_ids)}", "INFO")
                        await asyncio.sleep(0.5)
                    else:
                        return False, f"❌ Failed (HTTP {resp.status}) on chunk {i}: {text[:50]}"
            
            # --- CRITICAL FIX: INSTANTLY REMOVE FROM LOCAL MEMORY ---
            if range_name in state.numbers_data:
                del state.numbers_data[range_name]
                log(f"🗑️ Cleared {range_name} from local memory.", "INFO")
            # --------------------------------------------------------

            return True, f"✅ Removed {total_removed} numbers from {range_name}"

    except Exception as e:
        return False, str(e)
