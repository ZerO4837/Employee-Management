from __future__ import annotations

import os
from pathlib import Path
import sys


APP_NAME = "Digital Service Pakistan Employee App"
BUSINESS_NAME = "DIGITAL SERVICE PAKISTAN"
DEFAULT_USERNAME = "masabiha"
DEFAULT_PASSWORD = "Employee@7260"
ADMIN_USERNAME = "KillerPanel"
ADMIN_PASSWORD = "Compiler@Panel@675"
RESET_CODE = "2004212802"

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

SALES_FIELDS = [
    ("customer", "Customer Name", "entry", None),
    ("platform", "Order Source", "combo", ["WhatsApp", "Instagram", "Facebook", "Website", "Walk-in", "Other"]),
    ("order_id", "Order ID", "entry", None),
    ("item", "Item / Service", "entry", None),
    ("quantity", "Quantity", "entry", None),
    ("amount", "Sale Amount", "entry", None),
    ("payment", "Payment Method", "combo", ["Cash", "Bank Transfer", "JazzCash", "EasyPaisa", "Card", "Pending"]),
    ("status", "Order Status", "combo", ["Completed", "Processing", "Pending", "Cancelled"]),
]
