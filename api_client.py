import requests
import config

class IvaApi:
    """
    Handles HTTP requests to IVASMS (Add Number, Remove Range, Fetch Numbers).
    Requires active cookies and CSRF token from the browser session.
    """

    def __init__(self):
        self.session = requests.Session()
        # Headers specifically for AJAX requests
        self.headers = {
            "Host": "www.ivasms.com",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Referer": config.NUMBERS_URL
        }

    def add_number(self, term_id, cookies, csrf_token):
        """
        Adds a number by Termination ID.
        """
        if not csrf_token:
            return False, "❌ Error: No CSRF token available. Wait for bot to fully load."

        url = f"{config.NUMBERS_URL}/termination/number/add"
        data = {
            "_token": csrf_token,
            "id": str(term_id)
        }

        try:
            r = self.session.post(
                url,
                cookies=cookies,
                headers=self.headers,
                data=data,
                timeout=15
            )
            
            if r.status_code == 200:
                # The server usually returns a JSON with 'message'
                try:
                    msg = r.json().get("message", "Success")
                except:
                    msg = r.text[:100]
                return True, msg
            else:
                return False, f"HTTP Error {r.status_code}"

        except Exception as e:
            return False, str(e)

    def remove_range(self, range_name, number_ids, cookies, csrf_token):
        """
        Removes all numbers in a specific range.
        Requires the list of NumberIDs (which are fetched via fetch_numbers).
        """
        if not csrf_token:
            return False, "No CSRF token."
        
        if not number_ids:
            return False, f"No numbers found for range '{range_name}'."

        url = f"{config.NUMBERS_URL}/return/number/bluck"
        
        # Prepare payload: _token and array of IDs
        data = [("_token", csrf_token)]
        for nid in number_ids:
            data.append(("NumberID[]", str(nid)))

        try:
            r = self.session.post(
                url,
                cookies=cookies,
                headers=self.headers,
                data=data,
                timeout=15
            )
            
            if r.status_code == 200:
                try:
                    msg = r.json().get("message", "Removed successfully")
                except:
                    msg = "Removed successfully"
                return True, msg
            else:
                return False, f"HTTP {r.status_code}"

        except Exception as e:
            return False, str(e)

    def fetch_numbers(self, cookies):
        """
        Fetches the current list of numbers from the server.
        Returns: { 'RangeName': [list_of_numbers], ... }, { 'RangeName': [list_of_ids], ... }
        """
        groups = {}
        ids_by_group = {}
        start = 0
        page_size = 50

        try:
            while True:
                params = {
                    "start": start,
                    "length": page_size,
                    # Minimal params required by DataTables
                    "draw": 1,
                    "columns[0][data]": "number_id",
                    "order[0][column]": 1,
                    "order[0][dir]": "desc"
                }
                
                r = self.session.get(
                    config.NUMBERS_URL,
                    headers=self.headers,
                    cookies=cookies,
                    params=params,
                    timeout=15
                )

                if r.status_code != 200:
                    break

                data = r.json()
                rows = data.get("data", [])
                total = data.get("recordsTotal", 0)

                if not rows:
                    break

                for row in rows:
                    # Extract Number
                    num = str(row.get("Number")).strip()
                    
                    # Extract Range
                    rng = str(row.get("range") or "Unknown").strip()
                    
                    # Extract ID (hidden in HTML sometimes, or direct field)
                    # We need the ID to remove it later
                    raw_id = row.get("number_id", "")
                    # Usually looks like: <input ... value="12345">
                    import re
                    m = re.search(r'value="(\d+)"', str(raw_id))
                    num_id = m.group(1) if m else None

                    if num:
                        # Add to groups
                        if rng not in groups:
                            groups[rng] = []
                            ids_by_group[rng] = []
                        
                        groups[rng].append(num)
                        if num_id:
                            ids_by_group[rng].append(num_id)

                start += page_size
                if start >= total:
                    break
            
            return groups, ids_by_group

        except Exception as e:
            print(f"⚠️ Fetch Numbers Error: {e}")
            return {}, {}
