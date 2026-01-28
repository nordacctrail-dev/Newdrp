import aiohttp
import asyncio
import state
import config
from utils import log
import re
import time

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
                elif resp.status == 403:
                    return False, "⛔ 403 Forbidden (UA/Cookie Mismatch)"
                elif resp.status == 419:
                    return False, "⛔ 419 Page Expired (CSRF Token Invalid)"
                else:
                    return False, f"⚠️ Error {resp.status}: {text[:100]}"
    except Exception as e:
        return False, f"💥 Request Failed: {str(e)}"

async def fetch_numbers():
    """
    Refreshes the list of numbers.
    LOOPS correctly to fetch ALL pages using strict DataTables params.
    """
    url = config.NUMBERS_BASE_URL
    headers, cookies = await get_headers_and_cookies()
    
    BATCH_SIZE = 50  # Match t3s.py (safe size)
    start = 0
    draw = 1
    all_rows = []
    
    log("🔄 Starting bulk fetch of numbers...", "INFO")
    
    try:
        async with aiohttp.ClientSession(cookies=cookies) as session:
            while True:
                # Exact params from t3s.py to ensure server behaves correctly
                params = {
                    "draw": str(draw),
                    "columns[0][data]": "number_id",
                    "columns[0][name]": "id",
                    "columns[0][orderable]": "false",
                    "columns[1][data]": "Number",
                    "columns[2][data]": "range",
                    "columns[3][data]": "A2P",
                    "columns[13][data]": "action",
                    "order[0][column]": "1",
                    "order[0][dir]": "desc",
                    "start": str(start),
                    "length": str(BATCH_SIZE),
                    "search[value]": ""
                }
                
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status != 200:
                        return False, f"HTTP {resp.status} (Possible Cloudflare Block)"

                    data = await resp.json()
                    rows = data.get("data", [])
                    
                    # Determine Total Records (Handles 'recordsTotal' or 'recordsFiltered')
                    total_records = data.get("recordsTotal") or data.get("recordsFiltered") or 0
                    try:
                        total_records = int(total_records)
                    except:
                        total_records = 0
                    
                    if not rows:
                        break
                        
                    all_rows.extend(rows)
                    log(f"   Fetched {len(rows)} rows (Total: {len(all_rows)}/{total_records})", "INFO")
                    
                    # Stop if we fetched everything
                    if len(all_rows) >= total_records:
                        break
                        
                    # Stop if server returned fewer items than requested (last page)
                    if len(rows) < BATCH_SIZE:
                        break
                        
                    # Next Page
                    start += BATCH_SIZE
                    draw += 1
                    await asyncio.sleep(0.2) # Slight delay to be polite
                    
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
            
            return True, f"✅ Removed {total_removed} numbers from {range_name}"

    except Exception as e:
        return False, str(e)
