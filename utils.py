import os
import logging
from datetime import datetime
from typing import List, Tuple, Any

# ====================================================
# 1. LOGGING SETUP
# ====================================================
# Colors for terminal output
class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"

def log(msg: str, level: str = "INFO"):
    """Prints a structured log message with timestamp."""
    ts = datetime.now().strftime("%H:%M:%S")
    color = Colors.GREEN if level == "INFO" else Colors.RED if level == "ERROR" else Colors.YELLOW
    print(f"{Colors.RESET}[{ts}] {color}[{level}]{Colors.RESET} {msg}")

# ====================================================
# 2. NUMBER FORMATTING
# ====================================================
def fmt_num(num: Any) -> str:
    """Ensures phone numbers have a + prefix and no extra spaces."""
    if not num: return "Unknown"
    s = str(num).strip()
    if s.lower() in ["unknown", "n/a", "none", ""]: return "Unknown"
    # Remove existing + to avoid ++, then add it back
    clean = s.lstrip('+')
    return f"+{clean}"

# ====================================================
# 3. EXPORT MANAGER
# ====================================================
class ExportManager:
    @staticmethod
    def generate(numbers: List[Any], base_name: str) -> str:
        """
        Creates a .txt file in the 'exports' folder.
        Returns the file path.
        """
        # Ensure export directory exists
        export_dir = os.path.abspath("exports")
        os.makedirs(export_dir, exist_ok=True)

        # Create unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_name = "".join(x for x in base_name if x.isalnum() or x in "_-")
        filename = os.path.join(export_dir, f"{clean_name}_{timestamp}.txt")
        
        try:
            valid_nums = [str(n).strip() for n in numbers if n]
            content = "\n".join(valid_nums) if valid_nums else "No numbers found."

            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)
                
            return filename
        except Exception as e:
            log(f"Export Error: {e}", "ERROR")
            return None

# ====================================================
# 4. COUNTRY MANAGER (Flags & Names)
# ====================================================
class CountryManager:
    # Prefix -> (Country Name, Flag Emoji)
    PREFIX_DATA = {
        '1': ('USA/Canada', '🇺🇸'), '7': ('Russia', '🇷🇺'), '44': ('UK', '🇬🇧'),
        '33': ('France', '🇫🇷'), '49': ('Germany', '🇩🇪'), '34': ('Spain', '🇪🇸'),
        '55': ('Brazil', '🇧🇷'), '91': ('India', '🇮🇳'), '62': ('Indonesia', '🇮🇩'),
        '86': ('China', '🇨🇳'), '61': ('Australia', '🇦🇺'), '81': ('Japan', '🇯🇵'),
        '20': ('Egypt', '🇪🇬'), '27': ('South Africa', '🇿🇦'), '90': ('Turkey', '🇹🇷'),
        '31': ('Netherlands', '🇳🇱'), '39': ('Italy', '🇮🇹'), '48': ('Poland', '🇵🇱'),
        '380': ('Ukraine', '🇺🇦'), '84': ('Vietnam', '🇻🇳'), '66': ('Thailand', '🇹🇭'),
        '63': ('Philippines', '🇵🇭'), '60': ('Malaysia', '🇲🇾'), '92': ('Pakistan', '🇵🇰'),
        # Add more codes here if needed
    }

    @staticmethod
    def get_flag_by_name(country_name: str) -> str:
        """Returns the flag emoji for a given country name."""
        for name, flag in CountryManager.PREFIX_DATA.values():
            if name == country_name:
                return flag
        return "🏳️"

    @staticmethod
    def get_country(number: str) -> str:
        """Detects country name from phone number."""
        clean = ''.join(filter(str.isdigit, str(number)))
        # Check prefixes from length 3 down to 1
        for length in range(3, 0, -1):
            prefix = clean[:length]
            if prefix in CountryManager.PREFIX_DATA:
                return CountryManager.PREFIX_DATA[prefix][0]
        return "Other"
