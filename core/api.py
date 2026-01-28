import aiohttp
import state
import config
from utils import log
import re

async def get_headers_and_cookies():
    """
    Constructs headers and cookies using the LIVE browser state.
    CRITICAL: Must use the browser's User-Agent to match the cookies.
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
                else:
                    return False, f"⚠️ Error {resp.status}: {text[:100]}"
    except Exception as e:
        return False, f"💥 Request Failed: {str(e)}"

async def fetch_numbers():
    """
    Refreshes the list of numbers.
    Now extracts BOTH the actual 'Number' and the 'number_id'.
    """
    url = config.NUMBERS_BASE_URL
    headers, cookies = await get_headers_and_cookies()
    
    params = {
        "draw": "1",
        "start": "0",
        "length": str(config.NUMBERS_PAGE_SIZE),
        "search[value]": ""
    }

    try:
        async with aiohttp.ClientSession(cookies=cookies) as session:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    return False, f"HTTP {resp.status} (Possible Cloudflare Block)"

                data = await resp.json()
                rows = data.get("data", [])
                
                groups = {}
                
                for row in rows:
                    # 1. Get the actual phone number string
                    phone_number = row.get("Number")
                    if not phone_number: continue
                    phone_number = str(phone_number).strip()

                    # 2. Get the Range Name
                    rng = row.get("range", "Unknown")
                    
                    # 3. Extract the ID (hidden in HTML value="123")
                    # T3S logic: re.search(r'value="(\d+)"', num_id_html)
                    num_id_html = row.get("number_id", "")
                    num_id_match = re.search(r'value="(\d+)"', num_id_html)
                    
                    if num_id_match:
                        num_id = num_id_match.group(1)
                        
                        if rng not in groups: 
                            groups[rng] = []
                        
                        # STORE BOTH: Number for display, ID for deletion
                        groups[rng].append({
                            "number": phone_number,
                            "id": num_id
                        })

                # Update State with the rich data
                state.numbers_data = groups 
                state.numbers_last_update = __import__("time").time()
                
                total = sum(len(items) for items in groups.values())
                return True, f"Fetched {total} numbers in {len(groups)} ranges."
    except Exception as e:
        return False, str(e)

async def remove_range(range_name: str):
    """Removes all numbers in a specific range."""
    # Check if we have data for this range
    if not hasattr(state, "numbers_data") or range_name not in state.numbers_data:
        return False, "❌ Range not found. Please refresh numbers first."

    # Extract just the IDs for the API call
    items = state.numbers_data[range_name]
    ids = [item['id'] for item in items]
    
    if not ids:
        return False, "⚠️ No numbers found in this range."

    url = config.REMOVE_NUMBER_URL
    headers, cookies = await get_headers_and_cookies()
    
    data = aiohttp.FormData()
    data.add_field("_token", state.current_csrf_token)
    for num_id in ids:
        data.add_field("NumberID[]", num_id)

    try:
        async with aiohttp.ClientSession(cookies=cookies) as session:
            async with session.post(url, headers=headers, data=data) as resp:
                text = await resp.text()
                if resp.status == 200:
                    return True, f"✅ Removed {len(ids)} numbers from {range_name}"
                else:
                    return False, f"❌ Failed (HTTP {resp.status}): {text[:50]}"
    except Exception as e:
        return False, str(e)
