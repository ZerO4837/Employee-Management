from __future__ import annotations

import os
from pathlib import Path
import sys


APP_NAME = "Digital Service Pakistan Employee App"
BUSINESS_NAME = "DIGITAL SERVICE PAKISTAN"
APP_VERSION = "0.1.0"
UPDATE_REPO_OWNER = os.environ.get("DSP_UPDATE_REPO_OWNER", "ZerO4837")
UPDATE_REPO_NAME = os.environ.get("DSP_UPDATE_REPO_NAME", "Employee-Management")
UPDATE_BRANCH = os.environ.get("DSP_UPDATE_BRANCH", "main")
DEFAULT_USERNAME = os.environ.get("DSP_DEFAULT_USERNAME", "masabiha")
DEFAULT_PASSWORD = os.environ.get("DSP_DEFAULT_PASSWORD", "")
ADMIN_USERNAME = os.environ.get("DSP_ADMIN_USERNAME", "KillerPanel")
ADMIN_PASSWORD = os.environ.get("DSP_ADMIN_PASSWORD", "")
RESET_CODE = os.environ.get("DSP_RESET_CODE", "")

def _source_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return _source_root()


def _app_data_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Digital Service Pakistan" / "Employee Management"
    return Path.home() / "AppData" / "Local" / "Digital Service Pakistan" / "Employee Management"


BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else _source_root()
BUNDLE_DIR = _bundle_root()
ASSET_DIR = BUNDLE_DIR / "assets"
LOGO_PATH = ASSET_DIR / "logo.jpeg"
APP_ICON_PATH = ASSET_DIR / "app_icon.ico"
DATA_DIR = _app_data_root() if getattr(sys, "frozen", False) else BASE_DIR / "data"
AUTH_CONFIG_PATH = DATA_DIR / "auth_config.json"
APP_DB_PATH = DATA_DIR / "employee_management.sqlite3"
SUPABASE_CONFIG_PATH = DATA_DIR / "supabase_config.json"
MANAGED_SALES_WORKBOOK_PATH = DATA_DIR / "sales_workbook.xlsx"
SUPABASE_URL = os.environ.get("DSP_SUPABASE_URL", "").strip()
SUPABASE_ANON_KEY = os.environ.get("DSP_SUPABASE_ANON_KEY", "").strip()
SUPABASE_ADMIN_SECRET = os.environ.get("DSP_SUPABASE_ADMIN_SECRET", "").strip()
SUPABASE_EMPLOYEE_SYNC_SECRET = os.environ.get("DSP_SUPABASE_EMPLOYEE_SYNC_SECRET", "").strip()
try:
    SUPABASE_SYNC_INTERVAL_SECONDS = int(os.environ.get("DSP_SUPABASE_SYNC_INTERVAL_SECONDS", "15"))
except ValueError:
    SUPABASE_SYNC_INTERVAL_SECONDS = 15
_sales_workbook_setting = os.environ.get("DSP_SALES_WORKBOOK_PATH") or str(DATA_DIR / "sales_entries.xlsx")
SALES_WORKBOOK_PATH = Path(os.path.expandvars(_sales_workbook_setting)).expanduser()
SALES_WORKSHEET_NAME = os.environ.get("DSP_SALES_WORKSHEET_NAME", "").strip()
SALES_EXCEL_DATE_FORMAT = "d/m/yyyy"

NAVY = "#07063f"
NAVY_2 = "#0d1668"
NAVY_LIGHT = "#10136a"
BLUE = "#1267e8"
BLUE_DARK = "#0d4fb5"
SKY = "#eaf4ff"
TEAL = "#67d7e4"
CYAN = "#9cecfb"
BG = "#f4f8ff"
BG_2 = "#edf4ff"
WHITE = "#ffffff"
MUTED = "#5f6f89"
TEXT = "#14213d"
LINE = "#d9e4f2"
SUCCESS = "#0f8f63"
DANGER = "#c73d4b"
WARNING = "#b97913"

SIDEBAR_BG = "#050b24"
SIDEBAR_SURFACE = "#0b1433"
SIDEBAR_SURFACE_2 = "#101d45"
SIDEBAR_BORDER = "#20345f"
SIDEBAR_HOVER = "#16285c"
SIDEBAR_ACTIVE = "#eaf3ff"
SIDEBAR_ACTIVE_TEXT = "#08204a"
SIDEBAR_TEXT = "#d9e7ff"
SIDEBAR_MUTED = "#8fa8d2"
SIDEBAR_DISABLED = "#11182e"
SIDEBAR_DISABLED_TEXT = "#66789a"

FONT = "Segoe UI"
FONT_BOLD = "Segoe UI Semibold"

SALES_SERVICE_NAMES = [
    "5G IPTV Monthly",
    "Adobe Creative Cloud Monthly Own Email",
    "Adobe Creative Cloud Monthly Private",
    "Adobe Creative Cloud Monthly Shared",
    "B1G IPTV Monthly",
    "Capcut Private Monthly",
    "Chatgpt Private Monthly",
    "Chatgpt Shared Monthly",
    "Claude Pro Monthly",
    "HBO Max Screen",
    "Netflix Screens",
    "Nord VPN Private Monthly",
    "Nord VPN Shared Monthly",
    "Opplex IPTV Monthly",
    "Prime Video Monthly Full Account",
    "Prime Video Screen",
    "Prime Video Screen 6 month",
    "Proton VPN Private Monthly",
    "Proton VPN Shared Monthly",
    "Spotify Solo 6 Month",
    "Starshare IPTV Monthly",
    "Trex IPTV Monthly",
    "Windscribe VPN Shared Monthly",
    "Youtube Premium 6 Month",
    "Youtube Premium Monthly",
    "Youtube Premium Yearly",
    "Other",
]

SALES_FIELDS = [
    ("customer", "Customer Name", "entry", None),
    ("item", "Items Sold", "combo", SALES_SERVICE_NAMES),
    ("order_id", "Email/Order ID", "entry", None),
    ("buying_amount", "Buying Amount", "entry", None),
    ("selling_amount", "Selling Amount", "entry", None),
    ("status", "Status", "combo", ["Done", "Pending", "Cancelled", "Other"]),
]
