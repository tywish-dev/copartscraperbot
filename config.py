"""Application configuration loaded from environment variables."""

import os
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class SearchTarget(TypedDict, total=False):
    make: str
    models: list[str]
    min_year: int
    max_year: int
    all_models: bool


# --- Notification credentials ---
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM: str = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
WHATSAPP_TO_NUMBER: str = os.getenv("WHATSAPP_TO_NUMBER", "")
ENABLE_WHATSAPP: bool = os.getenv("ENABLE_WHATSAPP", "false").lower() in (
    "true",
    "1",
    "yes",
)

# --- Scheduler (hourly automatic checks + alerts) ---
CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "60"))

# --- Global search filters (applied on Copart + post-scrape) ---
MAX_ODOMETER: int = 999_999
MAX_YEAR: int = 2027
REQUIRE_CLEAN_TITLE: bool = True
ONLY_BUY_NOW: bool = False

# Copart damage_type_code values — matches your saved search link
ALLOWED_DAMAGE_CODES: list[str] = [
    "DAMAGECODE_FR",  # Front End
    "DAMAGECODE_MN",  # Minor Dent/Scratches
    "DAMAGECODE_NW",  # Normal Wear
    "DAMAGECODE_RR",  # Rear End
    "DAMAGECODE_SD",  # Side
    "DAMAGECODE_UN",  # Unknown
    "DAMAGECODE_VN",  # Vandalism
]

# Human-readable damage labels for post-scrape validation
ALLOWED_DAMAGE_KEYWORDS: list[str] = [
    "FRONT END",
    "MINOR DENT",
    "NORMAL WEAR",
    "REAR END",
    "SIDE",
    "UNKNOWN",
    "VANDALISM",
]

# Copart clean-title filter code (used for strict scrapes; union scrape is permissive)
CLEAN_TITLE_FILTER: str = "title_group_code:TITLEGROUP_C"

# Default watch list for new users (also used to seed first registered user)
DEFAULT_SEARCH_TARGETS: list[SearchTarget] = [
    {"make": "BMW", "models": ["M3", "M4"], "min_year": 2020, "max_year": 2027},
    {
        "make": "Porsche",
        "models": ["911", "Cayman", "Cayenne"],
        "min_year": 2010,
        "max_year": 2027,
    },
    {
        "make": "Chevrolet",
        "models": ["Corvette"],
        "min_year": 2017,
        "max_year": 2027,
    },
    {
        "make": "Tesla",
        "models": [],
        "min_year": 2022,
        "max_year": 2027,
        "all_models": True,
    },
]

# Legacy alias — prefer user_prefs.default_preferences() for per-user data
SEARCH_TARGETS: list[SearchTarget] = DEFAULT_SEARCH_TARGETS

# No state restriction — search nationwide
PREFERRED_LOCATIONS: list[str] = []

# --- Scraper settings ---
REQUEST_DELAY_SECONDS: float = 2.5
MAX_RETRIES: int = 3
SELENIUM_HEADLESS: bool = os.getenv("SELENIUM_HEADLESS", "true").lower() in ("true", "1", "yes")
SELENIUM_PAGE_TIMEOUT: int = int(os.getenv("SELENIUM_PAGE_TIMEOUT", "45"))
SEARCH_PAGE_SIZE: int = 100
MAX_SCRAPE_PAGES: int = int(os.getenv("MAX_SCRAPE_PAGES", "20"))
# Max simultaneous browser scrapes (/check for different users can run in parallel).
MAX_CONCURRENT_SCANS: int = int(os.getenv("MAX_CONCURRENT_SCANS", "2"))
BROWSER: str = os.getenv("BROWSER", "chrome").lower()
USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# --- Paths ---
_data_dir = os.getenv("DATA_DIR")
if _data_dir:
    _storage_root = Path(_data_dir)
    DATABASE_PATH: Path = _storage_root / "seen_lots.db"
    LOG_PATH: Path = _storage_root / "bot.log"
else:
    DATABASE_PATH = BASE_DIR / "seen_lots.db"
    LOG_PATH = BASE_DIR / "bot.log"

# Copart URLs
COPART_LOT_SEARCH_URL = "https://www.copart.com/lotSearchResults"
COPART_LOT_URL_TEMPLATE = "https://www.copart.com/lot/{lot_number}"
