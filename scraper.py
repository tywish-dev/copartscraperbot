"""Copart search and scraping with API, HTTP, and Selenium fallbacks."""

import json
import logging
import re
import time
from typing import Any

import requests
from bs4 import BeautifulSoup

import config
from filters import Lot

logger = logging.getLogger(__name__)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": config.USER_AGENT,
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.copart.com/",
    }
)


def _delay() -> None:
    time.sleep(config.REQUEST_DELAY_SECONDS)


def _request_with_backoff(
    method: str,
    url: str,
    **kwargs: Any,
) -> requests.Response | None:
    """Execute an HTTP request with exponential backoff on failure."""
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            _delay()
            response = SESSION.request(method, url, timeout=30, **kwargs)
            if response.status_code in (403, 429):
                logger.warning(
                    "Copart blocked request (%s) on attempt %d/%d",
                    response.status_code,
                    attempt,
                    config.MAX_RETRIES,
                )
                if attempt < config.MAX_RETRIES:
                    time.sleep(2**attempt)
                    continue
                return None
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            logger.error(
                "Request failed on attempt %d/%d: %s",
                attempt,
                config.MAX_RETRIES,
                exc,
            )
            if attempt < config.MAX_RETRIES:
                time.sleep(2**attempt)
            else:
                return None
    return None


def _build_search_query() -> str:
    makes = " ".join(config.PREFERRED_MAKES)
    return f"{makes} {config.MIN_YEAR}"


def _lot_url(lot_number: str) -> str:
    return config.COPART_LOT_URL_TEMPLATE.format(lot_number=lot_number)


def _parse_lot_record(raw: dict[str, Any]) -> Lot | None:
    """Normalize a raw Copart lot dict into a Lot dataclass."""
    lot_number = str(
        raw.get("lotNumberStr")
        or raw.get("ln")
        or raw.get("lotNumber")
        or raw.get("lot_number")
        or ""
    ).strip()
    if not lot_number:
        return None

    year_raw = raw.get("lcy") or raw.get("year") or raw.get("modelYear")
    year = int(year_raw) if year_raw else None

    make = str(raw.get("mkn") or raw.get("make") or raw.get("mk") or "Unknown")
    model = str(raw.get("mmod") or raw.get("model") or raw.get("md") or "")

    title = str(
        raw.get("ld")
        or raw.get("title")
        or raw.get("lotDesc")
        or f"{year or ''} {make} {model}".strip()
    )

    odometer_raw = raw.get("orr") or raw.get("odometer") or raw.get("od")
    odometer: int | None = None
    if odometer_raw is not None:
        odometer = int(re.sub(r"[^\d]", "", str(odometer_raw)) or 0) or None

    damage = str(
        raw.get("dd")
        or raw.get("damageType")
        or raw.get("damage")
        or raw.get("primaryDamage")
        or "Unknown"
    )

    repair_raw = raw.get("rc") or raw.get("estimatedRepairCost") or raw.get("repairCost")
    repair_cost: float | None = None
    if repair_raw is not None:
        repair_cost = float(re.sub(r"[^\d.]", "", str(repair_raw)) or 0) or None

    buy_now_raw = (
        raw.get("buyItNowPrice")
        or raw.get("buyNowPrice")
        or raw.get("bn")
        or raw.get("hb")
        or raw.get("highBid")
    )
    buy_now: float | None = None
    if buy_now_raw is not None:
        buy_now = float(re.sub(r"[^\d.]", "", str(buy_now_raw)) or 0) or None

    auction_date = str(
        raw.get("ad")
        or raw.get("auctionDate")
        or raw.get("auctionDateUtc")
        or "TBD"
    )

    location = str(
        raw.get("yn")
        or raw.get("location")
        or raw.get("loc")
        or raw.get("yardName")
        or "Unknown"
    )

    images: list[str] = []
    image_raw = raw.get("tims") or raw.get("images") or raw.get("img") or []
    if isinstance(image_raw, list):
        for img in image_raw:
            if isinstance(img, str):
                images.append(img)
            elif isinstance(img, dict):
                url = img.get("url") or img.get("fullUrl") or img.get("imageUrl")
                if url:
                    images.append(str(url))
    elif isinstance(image_raw, str) and image_raw:
        images.append(image_raw)

    return Lot(
        lot_number=lot_number,
        title=title.strip(),
        year=year,
        make=make.strip(),
        model=model.strip(),
        odometer=odometer,
        damage_type=damage.strip(),
        estimated_repair_cost=repair_cost,
        buy_now_price=buy_now,
        auction_date=auction_date.strip(),
        location=location.strip(),
        images=images,
        lot_url=_lot_url(lot_number),
    )


def _extract_lots_from_payload(data: Any) -> list[Lot]:
    """Walk common Copart JSON response shapes."""
    lots: list[Lot] = []
    candidates: list[dict[str, Any]] = []

    if isinstance(data, dict):
        for key in ("results", "data", "lots", "content", "returnCode"):
            value = data.get(key)
            if isinstance(value, list):
                candidates.extend(item for item in value if isinstance(item, dict))
            elif isinstance(value, dict):
                nested = value.get("results") or value.get("lots") or value.get("content")
                if isinstance(nested, list):
                    candidates.extend(item for item in nested if isinstance(item, dict))

        if not candidates and "lotNumberStr" in data:
            candidates.append(data)
    elif isinstance(data, list):
        candidates.extend(item for item in data if isinstance(item, dict))

    for raw in candidates:
        lot = _parse_lot_record(raw)
        if lot:
            lots.append(lot)

    return lots


def _fetch_via_api() -> list[Lot]:
    """Try the Copart public API search endpoint."""
    params = {
        "query": _build_search_query(),
        "page": 0,
        "size": 100,
        "filter": json.dumps(
            {
                "YEAR": [f"{config.MIN_YEAR}:2030"],
                "MAKE": config.PREFERRED_MAKES,
            }
        ),
    }
    logger.info("Attempting Copart API search")
    response = _request_with_backoff("GET", config.COPART_API_URL, params=params)
    if not response:
        return []

    try:
        data = response.json()
    except json.JSONDecodeError:
        logger.warning("API response was not valid JSON")
        return []

    lots = _extract_lots_from_payload(data)
    logger.info("API returned %d lots", len(lots))
    return lots


def _fetch_via_solr() -> list[Lot]:
    """Try Copart's Solr-backed public data endpoint."""
    payload = {
        "query": ["*"],
        "filter": {
            "MAKE": config.PREFERRED_MAKES,
            "YEAR": [f"{config.MIN_YEAR}:2030"],
        },
        "sort": ["auction_date_type desc", "auction_date_utc asc"],
        "page": 0,
        "size": 100,
    }
    logger.info("Attempting Copart Solr endpoint")
    response = _request_with_backoff(
        "POST",
        config.COPART_SOLR_URL,
        json=payload,
        headers={"Content-Type": "application/json"},
    )
    if not response:
        return []

    try:
        data = response.json()
    except json.JSONDecodeError:
        logger.warning("Solr response was not valid JSON")
        return []

    lots = _extract_lots_from_payload(data)
    logger.info("Solr returned %d lots", len(lots))
    return lots


def _fetch_via_html() -> list[Lot]:
    """Scrape the public search results HTML page."""
    logger.info("Attempting HTML scrape of search results")
    params = {"query": _build_search_query()}
    response = _request_with_backoff("GET", config.COPART_SEARCH_URL, params=params)
    if not response:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    lots: list[Lot] = []

    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        if not text or "lotNumber" not in text:
            continue
        for match in re.finditer(r"\{[^{}]*lotNumber[^{}]*\}", text):
            try:
                raw = json.loads(match.group())
                lot = _parse_lot_record(raw)
                if lot:
                    lots.append(lot)
            except json.JSONDecodeError:
                continue

    if lots:
        logger.info("HTML scrape extracted %d lots from embedded JSON", len(lots))
        return lots

    for row in soup.select("[data-lot-number], .lot-row, tr[data-uname='lotsearchLot']"):
        lot_number = (
            row.get("data-lot-number")
            or row.get("data-lot")
            or ""
        ).strip()
        if not lot_number:
            link = row.find("a", href=re.compile(r"/lot/\d+"))
            if link:
                href_match = re.search(r"/lot/(\d+)", link.get("href", ""))
                lot_number = href_match.group(1) if href_match else ""

        if not lot_number:
            continue

        title_el = row.find(class_=re.compile(r"title|desc|lot-desc", re.I))
        title = title_el.get_text(strip=True) if title_el else f"Lot {lot_number}"

        year, make, model = None, "Unknown", ""
        title_match = re.match(r"(\d{4})\s+(\S+)\s+(.*)", title)
        if title_match:
            year = int(title_match.group(1))
            make = title_match.group(2)
            model = title_match.group(3)

        lots.append(
            Lot(
                lot_number=lot_number,
                title=title,
                year=year,
                make=make,
                model=model,
                odometer=None,
                damage_type="Unknown",
                estimated_repair_cost=None,
                buy_now_price=None,
                auction_date="TBD",
                location="Unknown",
                images=[],
                lot_url=_lot_url(lot_number),
            )
        )

    logger.info("HTML scrape parsed %d lots", len(lots))
    return lots


def _fetch_via_selenium() -> list[Lot]:
    """Render the search page with undetected-chromedriver as a last resort."""
    try:
        import undetected_chromedriver as uc
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError:
        logger.error("Selenium/undetected-chromedriver not installed")
        return []

    logger.info("Falling back to Selenium browser scrape")
    driver = None
    lots: list[Lot] = []

    try:
        options = uc.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(f"user-agent={config.USER_AGENT}")

        driver = uc.Chrome(options=options)
        url = f"{config.COPART_SEARCH_URL}?query={_build_search_query()}"
        driver.get(url)

        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(5)

        page_source = driver.page_source
        soup = BeautifulSoup(page_source, "html.parser")

        for script in soup.find_all("script"):
            text = script.string or script.get_text()
            if not text:
                continue
            if "lotNumberStr" in text or "lotNumber" in text:
                for blob_match in re.finditer(r"\[\{.*?\}\]", text, re.DOTALL):
                    try:
                        data = json.loads(blob_match.group())
                        lots.extend(_extract_lots_from_payload(data))
                    except json.JSONDecodeError:
                        continue

        if not lots:
            for el in driver.find_elements(By.CSS_SELECTOR, "[data-uname='lotsearchLot']"):
                lot_number = el.get_attribute("data-lot-number") or ""
                if lot_number:
                    lots.append(
                        Lot(
                            lot_number=lot_number,
                            title=f"Lot {lot_number}",
                            year=None,
                            make="Unknown",
                            model="",
                            odometer=None,
                            damage_type="Unknown",
                            estimated_repair_cost=None,
                            buy_now_price=None,
                            auction_date="TBD",
                            location="Unknown",
                            images=[],
                            lot_url=_lot_url(lot_number),
                        )
                    )

        logger.info("Selenium scrape returned %d lots", len(lots))
    except Exception as exc:
        logger.error("Selenium scrape failed: %s", exc)
    finally:
        if driver:
            driver.quit()

    return lots


def scrape_lots() -> list[Lot]:
    """
    Search Copart using multiple strategies until lots are found.

    Order: public API -> Solr endpoint -> HTML scrape -> Selenium.
    """
    strategies = [
        ("api", _fetch_via_api),
        ("solr", _fetch_via_solr),
        ("html", _fetch_via_html),
        ("selenium", _fetch_via_selenium),
    ]

    for name, strategy in strategies:
        try:
            lots = strategy()
            if lots:
                logger.info("Scrape succeeded via %s with %d lots", name, len(lots))
                return _dedupe_lots(lots)
            logger.info("Strategy %s returned no lots, trying next", name)
        except Exception as exc:
            logger.error("Strategy %s failed: %s", name, exc)

    logger.warning("All scrape strategies exhausted with no results")
    return []


def _dedupe_lots(lots: list[Lot]) -> list[Lot]:
    seen: set[str] = set()
    unique: list[Lot] = []
    for lot in lots:
        if lot.lot_number not in seen:
            seen.add(lot.lot_number)
            unique.append(lot)
    return unique
