import aiohttp
import state
import config
from utils import log

async def get_headers_and_cookies():
    """
    Constructs headers and cookies using the LIVE browser state.
    CRITICAL: Must use the browser's User-Agent to match the cookies.
    """
    # 1. Get Cookies from Browser State
    cookies = state.current_cookies.copy()
    
    # 2. Get Base Headers from Config
    headers = config.NUMBERS_HEADERS.copy()
    
    # 3. OVERRIDE USER-AGENT (The Fix)
    # We must use the UA captured from the browser. 
    # If we use the hardcoded one, the server will reject the cookies.
    if getattr(state, "current_user_agent", None):
        headers["User-Agent"] = state.current_user_agent
    else:
        log("⚠️ API Warning: Browser User-Agent not captured yet. API calls may fail.", "WARN")

    # 4. Add CSRF Token (Required for POST requests)
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
                    return False, "⛔ 403 Forbidden (User-Agent/Cookie Mismatch)"
                elif resp.status == 419:
                    return False, "⛔ 419 Page Expired (CSRF Token Invalid)"
                else:
                    return False, f"⚠️ Error {resp.status}: {text[:100]}"
    except Exception as e:
        return False, f"💥 Request Failed: {str(e)}"

async def fetch_numbers():
    """Refreshes the list of numbers and groups them by Range."""
    url = config.NUMBERS_BASE_URL
    headers, cookies = await get_headers_and_cookies()
    
    # IVASMS uses server-side pagination (DataTables)
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
                import re
                
                # Parse the HTML fields in the JSON response
                for row in rows:
                    rng = row.get("range", "Unknown")
                    
                    # Extract Number ID from the HTML string: <input value="12345"...>
                    num_id_match = re.search(r'value="(\d+)"', row.get("number_id", ""))
                    
                    if num_id_match:
                        num_id = num_id_match.group(1)
                        if rng not in groups: 
                            groups[rng] = []
                        groups[rng].append(num_id)

                state.numbers_ids_by_group = groups
                state.numbers_last_update = __import__("time").time()
                return True, f"Fetched {len(rows)} numbers in {len(groups)} ranges."
    except Exception as e:
        return False, str(e)

async def remove_range(range_name: str):
    """Removes all numbers in a specific range."""
    if range_name not in state.numbers_ids_by_group:
        return False, "❌ Range not found. Please refresh numbers first."

    ids = state.numbers_ids_by_group[range_name]
    if not ids:
        return False, "⚠️ No numbers found in this range locally."

    url = config.REMOVE_NUMBER_URL
    headers, cookies = await get_headers_and_cookies()
    
    # Construct FormData for multiple IDs
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
