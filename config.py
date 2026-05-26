"""Application configuration loaded from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

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

# --- Scheduler ---
CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "30"))

# --- Car preferences ---
PREFERRED_MAKES: list[str] = ["BMW", "Mercedes", "Audi", "Toyota"]
MAX_ODOMETER: int = 120_000  # miles
MAX_BUY_NOW_PRICE: int = 8_000  # USD
MIN_YEAR: int = 2015
EXCLUDED_DAMAGE: list[str] = ["FIRE", "FLOOD", "VANDALISM"]
ONLY_BUY_NOW: bool = True
PREFERRED_LOCATIONS: list[str] = ["TX", "CA", "FL"]

# --- Scraper settings ---
REQUEST_DELAY_SECONDS: float = 2.5
MAX_RETRIES: int = 3
USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# --- Paths ---
DATABASE_PATH: Path = BASE_DIR / "seen_lots.db"
LOG_PATH: Path = BASE_DIR / "bot.log"

# Copart endpoints
COPART_API_URL = "https://api.copart.com/public/lots/search"
COPART_SEARCH_URL = "https://www.copart.com/public/lots/search-results"
COPART_SOLR_URL = "https://www.copart.com/public/data/lotdetails/solr/lots"
COPART_LOT_URL_TEMPLATE = "https://www.copart.com/lot/{lot_number}"
