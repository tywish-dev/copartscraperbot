"""Copart website scraper using browser rendering (Selenium)."""

import json
import logging
import os
import re
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import config
from filters import Lot

logger = logging.getLogger(__name__)

# Copart uses specific make strings in searchCriteria filters.
COPART_MAKE_NAMES: dict[str, str] = {
    "BMW": "BMW",
    "MERCEDES": "MERCEDES-BENZ",
    "MERCEDES-BENZ": "MERCEDES-BENZ",
    "AUDI": "AUDI",
    "TOYOTA": "TOYOTA",
    "TESLA": "TESLA",
    "HONDA": "HONDA",
    "FORD": "FORD",
    "CHEVROLET": "CHEVROLET",
    "CHEVY": "CHEVROLET",
    "NISSAN": "NISSAN",
    "LEXUS": "LEXUS",
    "PORSCHE": "PORSCHE",
}


def _lot_url(lot_number: str) -> str:
    return config.COPART_LOT_URL_TEMPLATE.format(lot_number=lot_number)


def _copart_make(make: str) -> str:
    key = make.strip().upper()
    return COPART_MAKE_NAMES.get(key, make.strip().upper())


def _max_search_year() -> int:
    return config.MAX_YEAR


def _build_search_criteria(
    make: str,
    model: str | None = None,
    min_year: int | None = None,
    max_year: int | None = None,
    permissive: bool = True,
) -> dict[str, Any]:
    """Build the searchCriteria JSON object Copart expects."""
    year_from = min_year if min_year is not None else 2010
    year_to = max_year if max_year is not None else config.MAX_YEAR

    filters: dict[str, list[str]] = {
        "PRID": [f"damage_type_code:{code}" for code in config.ALLOWED_DAMAGE_CODES],
        "ODM": [f"odometer_reading_received:[0 TO {config.MAX_ODOMETER}]"],
        "YEAR": [f"lot_year:[{year_from} TO {year_to}]"],
        "VEHT": ["vehicle_type_code:VEHTYPE_V"],
        "MAKE": [f'lot_make_desc:"{_copart_make(make)}"'],
    }
    if not permissive:
        filters["TITL"] = [config.CLEAN_TITLE_FILTER]
    if model:
        filters["MODL"] = [f'lot_model_desc:"{model.upper()}"']

    return {
        "query": ["*"],
        "filter": filters,
        "searchName": "",
        "watchListOnly": False,
        "freeFormSearch": False,
    }


def _build_display_str(
    make: str,
    model: str | None = None,
    min_year: int | None = None,
    max_year: int | None = None,
) -> str:
    year_from = min_year if min_year is not None else 2010
    year_to = max_year if max_year is not None else config.MAX_YEAR
    parts = [
        "AUTOMOBILE",
        "NORMAL WEAR",
        f"[0 TO {config.MAX_ODOMETER}]",
        f"[{year_from} TO {year_to}]",
    ]
    if model:
        parts.append(model)
    elif make:
        parts.append(_copart_make(make).title())
    return ",".join(parts)


def build_search_url(
    make: str,
    model: str | None = None,
    min_year: int | None = None,
    max_year: int | None = None,
) -> str:
    """Build a Copart lotSearchResults URL matching the site's filter format."""
    search_criteria = _build_search_criteria(make, model, min_year, max_year)
    params = {
        "free": "false",
        "displayStr": _build_display_str(make, model, min_year, max_year),
        "from": "/vehicleFinder",
        "fromSource": "widget",
        "qId": f"{uuid.uuid4()}-{int(time.time() * 1000)}",
        "searchCriteria": json.dumps(search_criteria, separators=(",", ":")),
    }
    return f"{config.COPART_LOT_SEARCH_URL}?{urlencode(params)}"


def build_union_search_targets(
    all_prefs: list,
) -> list[tuple[str, str | None, int, int, str]]:
    """Build deduped Copart search URLs from all active users' watch lists."""
    from user_prefs import UserPreferences, iter_scrape_entries

    seen: set[tuple[str, str | None, int, int]] = set()
    targets: list[tuple[str, str | None, int, int, str]] = []

    for prefs in all_prefs:
        if not isinstance(prefs, UserPreferences):
            continue
        for make, model, min_year, max_year in iter_scrape_entries(prefs):
            key = (make.upper(), model.upper() if model else None, min_year, max_year)
            if key in seen:
                continue
            seen.add(key)
            targets.append(
                (
                    make,
                    model,
                    min_year,
                    max_year,
                    build_search_url(make, model, min_year, max_year),
                )
            )
    return targets


def _build_search_targets() -> list[tuple[str, str | None, int, int, str]]:
    """Legacy helper using global default watch list."""
    from user_prefs import default_preferences

    return build_union_search_targets([default_preferences()])


def _parse_price(text: str) -> float | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
    if not cleaned:
        return None
    value = float(cleaned)
    return value if value > 0 else None


def _parse_odometer(text: str) -> int | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d]", "", text.replace(",", ""))
    return int(cleaned) if cleaned else None


def _parse_title_parts(title: str) -> tuple[int | None, str, str]:
    match = re.match(r"(\d{4})\s+(\S+)\s+(.*)", title.strip())
    if match:
        return int(match.group(1)), match.group(2), match.group(3).strip()
    return None, "Unknown", title.strip()


def _parse_lot_record(raw: dict[str, Any]) -> Lot | None:
    """Normalize a raw Copart lot dict (from in-browser XHR) into a Lot."""
    lot_number = str(
        raw.get("lotNumberStr")
        or raw.get("ln")
        or raw.get("lotNumber")
        or ""
    ).strip()
    if not lot_number:
        return None

    year_raw = raw.get("lcy") or raw.get("year")
    year = int(year_raw) if year_raw else None

    make = str(raw.get("mkn") or raw.get("make") or "Unknown")
    model = str(raw.get("mmod") or raw.get("model") or "")
    title = str(
        raw.get("ld")
        or raw.get("lotDesc")
        or f"{year or ''} {make} {model}".strip()
    )

    odometer_raw = raw.get("orr") or raw.get("odometer")
    odometer: int | None = None
    if odometer_raw is not None:
        odometer = _parse_odometer(str(odometer_raw))

    damage = str(raw.get("dd") or raw.get("damage") or raw.get("primaryDamage") or "Unknown")

    repair_raw = raw.get("rc") or raw.get("repairCost")
    repair_cost = _parse_price(str(repair_raw)) if repair_raw is not None else None

    buy_now_raw = (
        raw.get("buyItNowPrice")
        or raw.get("buyNowPrice")
        or raw.get("bn")
        or raw.get("hb")
    )
    buy_now = _parse_price(str(buy_now_raw)) if buy_now_raw is not None else None

    auction_date = str(raw.get("ad") or raw.get("auctionDate") or "TBD")
    location = str(raw.get("yn") or raw.get("loc") or raw.get("yardName") or "Unknown")

    images: list[str] = []
    image_raw = raw.get("tims") or raw.get("images") or []
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

    if not year or make == "Unknown":
        parsed_year, parsed_make, parsed_model = _parse_title_parts(title)
        year = year or parsed_year
        if make == "Unknown":
            make = parsed_make
        if not model:
            model = parsed_model

    title_status = str(
        raw.get("tsn")
        or raw.get("titleGroup")
        or raw.get("titleType")
        or ""
    )

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
        title_status=title_status,
    )


def _search_criteria_from_url(url: str) -> dict[str, Any] | None:
    """Extract searchCriteria JSON embedded in a lotSearchResults URL."""
    try:
        query = parse_qs(urlparse(url).query)
        raw = query.get("searchCriteria", [None])[0]
        if raw:
            return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.debug("Could not parse searchCriteria from URL: %s", exc)
    return None


def _xhr_payload_from_criteria(
    search_criteria: dict[str, Any], page: int
) -> dict[str, Any]:
    """Build Solr POST body matching the Copart frontend request shape."""
    payload = {
        "query": search_criteria.get("query", ["*"]),
        "filter": search_criteria.get("filter", {}),
        "searchName": search_criteria.get("searchName", ""),
        "watchListOnly": search_criteria.get("watchListOnly", False),
        "freeFormSearch": search_criteria.get("freeFormSearch", False),
        "sort": ["auction_date_type desc", "auction_date_utc asc"],
        "page": page,
        "size": config.SEARCH_PAGE_SIZE,
    }
    return payload


def _extract_lots_from_payload(data: Any) -> list[Lot]:
    lots: list[Lot] = []
    candidates: list[dict[str, Any]] = []

    if isinstance(data, dict):
        if data.get("returnCode") == -1:
            return []

        for key in ("results", "data", "lots", "content"):
            value = data.get(key)
            if isinstance(value, list):
                candidates.extend(item for item in value if isinstance(item, dict))
            elif isinstance(value, dict):
                nested = (
                    value.get("results")
                    or value.get("lots")
                    or value.get("content")
                )
                if isinstance(nested, list):
                    candidates.extend(item for item in nested if isinstance(item, dict))
                elif isinstance(nested, dict):
                    inner = nested.get("content") or nested.get("results")
                    if isinstance(inner, list):
                        candidates.extend(item for item in inner if isinstance(item, dict))

        if not candidates and "lotNumberStr" in data:
            candidates.append(data)
    elif isinstance(data, list):
        candidates.extend(item for item in data if isinstance(item, dict))

    for raw in candidates:
        lot = _parse_lot_record(raw)
        if lot:
            lots.append(lot)

    return lots


def _fetch_lots_xhr_page(driver, payload: dict[str, Any]) -> list[Lot]:
    """Fetch a single page of lots via in-browser XHR."""
    script = """
        const payload = arguments[0];
        const callback = arguments[arguments.length - 1];
        fetch("https://www.copart.com/public/data/lotdetails/solr/lots", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
            },
            body: JSON.stringify(payload),
            credentials: "include",
        })
        .then(r => r.text())
        .then(text => {
            try {
                callback({ ok: true, body: JSON.parse(text) });
            } catch (e) {
                callback({ ok: false, error: "invalid json: " + text.slice(0, 300) });
            }
        })
        .catch(err => callback({ ok: false, error: String(err) }));
    """
    try:
        result = driver.execute_async_script(script, payload)
    except Exception as exc:
        logger.warning("In-browser XHR failed: %s", exc)
        return []

    if not isinstance(result, dict) or not result.get("ok"):
        logger.warning(
            "In-browser XHR returned error: %s",
            result.get("error") if isinstance(result, dict) else result,
        )
        return []

    body = result.get("body")
    lots = _extract_lots_from_payload(body)
    if not lots and isinstance(body, dict):
        logger.warning(
            "XHR page %s empty — returnCode=%s desc=%s",
            payload.get("page"),
            body.get("returnCode"),
            body.get("returnCodeDesc") or body.get("data"),
        )
    return lots


def _fetch_all_lots_via_browser_xhr(
    driver, search_criteria: dict[str, Any]
) -> list[Lot]:
    """Paginate through Copart Solr results inside the browser session."""
    all_lots: list[Lot] = []

    for page in range(config.MAX_SCRAPE_PAGES):
        payload = _xhr_payload_from_criteria(search_criteria, page)
        batch = _fetch_lots_xhr_page(driver, payload)
        if not batch:
            if page == 0:
                logger.info("In-browser XHR returned no lots on page 0")
            break

        all_lots.extend(batch)
        logger.info("In-browser XHR page %d returned %d lots", page, len(batch))

        if len(batch) < config.SEARCH_PAGE_SIZE:
            break

        time.sleep(config.REQUEST_DELAY_SECONDS)

    deduped = _dedupe_lots(all_lots)
    logger.info("In-browser XHR total: %d unique lots", len(deduped))
    return deduped


def _create_edge_driver():
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options as EdgeOptions
    from selenium.webdriver.edge.service import Service as EdgeService
    from webdriver_manager.microsoft import EdgeChromiumDriverManager

    options = EdgeOptions()
    if config.SELENIUM_HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"--user-agent={config.USER_AGENT}")

    service = EdgeService(EdgeChromiumDriverManager().install())
    driver = webdriver.Edge(service=service, options=options)
    logger.info("Started Microsoft Edge browser")
    return driver


def _find_chrome_binary() -> str | None:
    """Locate Google Chrome executable on the system."""
    env_binary = os.getenv("CHROME_BIN", "").strip()
    if env_binary and os.path.exists(env_binary):
        return env_binary

    candidates = [
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        candidates.append(
            os.path.join(local_app, "Google", "Chrome", "Application", "chrome.exe")
        )

    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _get_chrome_major_version(chrome_binary: str | None) -> int | None:
    """Read installed Chrome major version for matching ChromeDriver."""
    import subprocess

    # Windows: chrome.exe --version often prints nothing; read Last Version file.
    if os.name == "nt":
        version_paths = [
            os.path.join(
                os.environ.get("LOCALAPPDATA", ""),
                "Google",
                "Chrome",
                "User Data",
                "Last Version",
            ),
            os.path.join(
                os.environ.get("PROGRAMFILES", ""),
                "Google",
                "Chrome",
                "Application",
                "Last Version",
            ),
        ]
        for path in version_paths:
            try:
                if os.path.isfile(path):
                    version_text = open(path, encoding="utf-8").read().strip()
                    match = re.search(r"(\d+)\.", version_text)
                    if match:
                        return int(match.group(1))
            except OSError:
                continue

    binary = chrome_binary or _find_chrome_binary()
    if not binary:
        return None

    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        output = (result.stdout or result.stderr or "").strip()
        match = re.search(r"(\d+)\.", output)
        if match:
            return int(match.group(1))
    except Exception as exc:
        logger.debug("Could not detect Chrome version: %s", exc)

    return None


def _create_chrome_driver():
    """Start undetected Chrome with a driver matched to the installed version."""
    import undetected_chromedriver as uc

    chrome_binary = _find_chrome_binary()
    if not chrome_binary:
        raise RuntimeError(
            "Google Chrome not found. Install Chrome or set BROWSER=edge in .env"
        )

    version_main = _get_chrome_major_version(chrome_binary)
    logger.info(
        "Using Chrome at %s (version %s)",
        chrome_binary,
        version_main or "unknown",
    )

    options = uc.ChromeOptions()
    options.binary_location = chrome_binary
    if config.SELENIUM_HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"--user-agent={config.USER_AGENT}")

    uc_kwargs: dict[str, Any] = {"options": options}
    if version_main:
        uc_kwargs["version_main"] = version_main

    try:
        driver = uc.Chrome(**uc_kwargs)
    except Exception as exc:
        logger.warning("undetected-chromedriver failed (%s), trying webdriver-manager", exc)
        driver = _create_chrome_driver_via_manager(chrome_binary)

    logger.info("Started Google Chrome browser")
    return driver


def _create_chrome_driver_via_manager(chrome_binary: str):
    """Fallback Chrome setup using webdriver-manager for driver version matching."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.chrome.service import Service as ChromeService
    from webdriver_manager.chrome import ChromeDriverManager

    options = ChromeOptions()
    options.binary_location = chrome_binary
    if config.SELENIUM_HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"--user-agent={config.USER_AGENT}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = ChromeService(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def _create_driver():
    """
    Create a browser WebDriver.

    Uses Edge or Chrome based on BROWSER config ("edge", "chrome", or "auto").
    """
    last_error: Exception | None = None

    if config.BROWSER == "edge":
        return _create_edge_driver()

    if config.BROWSER == "chrome":
        return _create_chrome_driver()

    # auto: prefer Chrome, fall back to Edge
    try:
        return _create_chrome_driver()
    except Exception as exc:
        last_error = exc
        logger.warning("Chrome unavailable (%s), trying Edge", exc)

    try:
        return _create_edge_driver()
    except Exception as exc:
        logger.error(
            "Could not start a browser. Set BROWSER=edge or BROWSER=chrome in .env. "
            "Last error: %s (prior: %s)",
            exc,
            last_error,
        )
        raise


def _dismiss_cookie_banner(driver) -> None:
    """Click Copart cookie/consent banners if present."""
    from selenium.webdriver.common.by import By

    selectors = [
        "#onetrust-accept-btn-handler",
        "button[data-uname='acceptCookiePolicy']",
        "button.accept-cookies",
        "button#acceptCookie",
    ]
    for selector in selectors:
        try:
            buttons = driver.find_elements(By.CSS_SELECTOR, selector)
            for button in buttons:
                if button.is_displayed():
                    button.click()
                    time.sleep(1)
                    logger.info("Dismissed cookie banner via %s", selector)
                    return
        except Exception:
            continue


def _wait_for_results(driver) -> bool:
    """Wait until search results or a no-results message appears."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    result_selectors = [
        "table tbody tr",
        "tr[data-lotnumber]",
        "tr[data-uname='lotsearchLot']",
        "[data-uname='lotsearchLotdesc']",
        ".search_result_lot_detail",
        "table#serverSideDataTable tbody tr",
    ]
    no_result_selectors = [
        "[data-uname='noResultsFound']",
        ".noresult-content",
        "#no-results-msg",
    ]

    def _results_loaded(d):
        for selector in result_selectors:
            if d.find_elements(By.CSS_SELECTOR, selector):
                return True
        for selector in no_result_selectors:
            if d.find_elements(By.CSS_SELECTOR, selector):
                return True
        return False

    try:
        WebDriverWait(driver, config.SELENIUM_PAGE_TIMEOUT).until(_results_loaded)
        return True
    except Exception:
        logger.warning("Timed out waiting for Copart search results to render")
        return False


def _safe_row_text(row, selector: str) -> str:
    from selenium.webdriver.common.by import By

    try:
        element = row.find_element(By.CSS_SELECTOR, selector)
        return (element.text or element.get_attribute("textContent") or "").strip()
    except Exception:
        return ""


def _safe_row_attr(row, selector: str, attribute: str) -> str:
    from selenium.webdriver.common.by import By

    try:
        if selector:
            element = row.find_element(By.CSS_SELECTOR, selector)
        else:
            element = row
        return (element.get_attribute(attribute) or "").strip()
    except Exception:
        return ""


def _parse_fields_from_row_text(row_text: str) -> dict[str, str | int | float | None]:
    """Parse Copart PrimeNG table row plain text into structured fields."""
    fields: dict[str, str | int | float | None] = {
        "odometer": None,
        "damage": "Unknown",
        "location": "Unknown",
        "auction_date": "TBD",
        "buy_now_price": None,
        "title_status": "",
    }

    odo_match = re.search(r"Odometer\s+([\d,]+)", row_text)
    if odo_match:
        fields["odometer"] = _parse_odometer(odo_match.group(1))

    for line in row_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if "TITLE" in upper:
            fields["title_status"] = stripped
        if stripped.endswith("Damage") or re.search(r"\bDamage\b", stripped):
            if "Damage" in stripped and stripped not in ("Damage", "Primary Damage"):
                fields["damage"] = stripped
        if re.match(r"^[A-Z]{2}\s*-\s*.+", stripped):
            fields["location"] = stripped

    auction_match = re.search(r"Auction in\s+(.+)", row_text)
    if auction_match:
        fields["auction_date"] = auction_match.group(1).strip()

    buy_now_match = re.search(
        r"Buy(?:\s+it)?\s+now[:\s]*\$?\s*([\d,]+(?:\.\d+)?)",
        row_text,
        re.IGNORECASE,
    )
    if buy_now_match:
        fields["buy_now_price"] = _parse_price(buy_now_match.group(1))

    return fields


def _extract_lot_number_from_row(row) -> str:
    from selenium.webdriver.common.by import By

    lot_number = (
        _safe_row_attr(row, "", "data-lotnumber")
        or _safe_row_attr(row, "[data-lot-number]", "data-lot-number")
    )
    if lot_number:
        return lot_number

    lot_number = _safe_row_text(row, ".search_result_lot_number")
    if lot_number:
        digits = re.sub(r"[^\d]", "", lot_number)
        if digits:
            return digits

    for link in row.find_elements(By.CSS_SELECTOR, "a[href*='/lot/']"):
        href = link.get_attribute("href") or ""
        match = re.search(r"/lot/(\d+)", href)
        if match:
            return match.group(1)

    return ""


def _parse_lot_from_row(row, fallback_make: str, fallback_model: str | None) -> Lot | None:
    """Parse a single search-results table row from the rendered DOM."""
    lot_number = _extract_lot_number_from_row(row)
    if not lot_number:
        return None

    title = (
        _safe_row_text(row, ".search_result_lot_detail")
        or _safe_row_text(row, "[data-uname='lotsearchLotdesc']")
        or _safe_row_text(row, "a[data-uname='lotsearchLotdesc']")
        or _safe_row_text(row, ".search-result-title")
    )
    if not title:
        title = f"Lot {lot_number}"

    year, make, model = _parse_title_parts(title)
    if make == "Unknown":
        make = fallback_make
    if not model and fallback_model:
        model = fallback_model

    row_text = (row.text or "").strip()
    parsed = _parse_fields_from_row_text(row_text)

    odometer = parsed["odometer"]
    if odometer is None:
        odometer = _parse_odometer(
            _safe_row_text(row, "[data-uname='lotsearchOdometer']")
            or _safe_row_text(row, "[data-uname='lotsearchLotodometer']")
        )

    damage = str(parsed["damage"])
    if damage == "Unknown":
        damage = (
            _safe_row_text(row, "[data-uname='lotsearchDamage']")
            or _safe_row_text(row, "[data-uname='lotsearchLotdamage']")
            or "Unknown"
        )

    location = str(parsed["location"])
    if location == "Unknown":
        location = (
            _safe_row_text(row, "[class*='yard']")
            or _safe_row_text(row, "[data-uname='lotsearchLocation']")
            or "Unknown"
        )

    auction_date = str(parsed["auction_date"])
    if auction_date == "TBD":
        auction_date = (
            _safe_row_text(row, "[data-uname='lotsearchSaletime']")
            or _safe_row_text(row, "[data-uname='lotsearchAuctiondate']")
            or "TBD"
        )

    buy_now = parsed["buy_now_price"]
    if buy_now is None:
        buy_now = _parse_price(
            _safe_row_text(row, "[data-uname='lotsearchBuyitnow']")
            or _safe_row_text(row, "[data-uname='lotsearchBuynow']")
        )

    image_url = (
        _safe_row_attr(row, "img[alt='Lot Image']", "src")
        or _safe_row_attr(row, "img[data-uname='lotsearchLotimage']", "src")
        or _safe_row_attr(row, "img", "src")
    )
    images = [image_url] if image_url and image_url.startswith("http") else []

    title_status = str(parsed.get("title_status") or "")
    if not title_status:
        from selenium.webdriver.common.by import By

        for link in row.find_elements(By.CSS_SELECTOR, "a[href*='/lot/']"):
            href = (link.get_attribute("href") or "").lower()
            if "clean-title" in href:
                title_status = "Clean Title"
                break

    return Lot(
        lot_number=lot_number,
        title=title,
        year=year,
        make=make,
        model=model,
        odometer=odometer if isinstance(odometer, int) else None,
        damage_type=damage,
        estimated_repair_cost=None,
        buy_now_price=buy_now if isinstance(buy_now, float) else None,
        auction_date=auction_date,
        location=location,
        images=images,
        lot_url=_lot_url(lot_number),
        title_status=title_status,
    )


def _find_result_rows(driver) -> list:
    """Return all lot rows on the current results page."""
    from selenium.webdriver.common.by import By

    row_selectors = [
        "table tbody tr",
        "tr[data-lotnumber]",
        "tr[data-uname='lotsearchLot']",
    ]

    for selector in row_selectors:
        rows = driver.find_elements(By.CSS_SELECTOR, selector)
        if rows:
            return rows
    return []


def _parse_dom_lots_current_page(
    driver, fallback_make: str, fallback_model: str | None
) -> list[Lot]:
    """Extract lots from the currently visible paginator page."""
    rows = _find_result_rows(driver)
    lots: list[Lot] = []

    for row in rows:
        try:
            lot = _parse_lot_from_row(row, fallback_make, fallback_model)
            if lot:
                lots.append(lot)
        except Exception as exc:
            logger.debug("Skipping row parse error: %s", exc)

    return lots


def _click_next_page(driver) -> bool:
    """Click the Copart PrimeNG paginator next button if available."""
    from selenium.webdriver.common.by import By

    selectors = [
        "button.p-paginator-next:not(.p-disabled)",
        ".p-paginator-next:not(.p-disabled)",
        "a.p-paginator-next:not(.p-disabled)",
    ]
    for selector in selectors:
        for button in driver.find_elements(By.CSS_SELECTOR, selector):
            classes = button.get_attribute("class") or ""
            if "p-disabled" in classes:
                continue
            if button.is_displayed() and button.is_enabled():
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", button)
                    time.sleep(0.5)
                    button.click()
                    time.sleep(2)
                    return True
                except Exception:
                    continue
    return False


def _parse_dom_lots_with_pagination(
    driver, fallback_make: str, fallback_model: str | None
) -> list[Lot]:
    """Walk every paginator page and parse all table rows on each."""
    all_lots: dict[str, Lot] = {}

    for page in range(config.MAX_SCRAPE_PAGES):
        before_first = _first_visible_lot_number(driver)
        batch = _parse_dom_lots_current_page(driver, fallback_make, fallback_model)
        if not batch:
            if page == 0:
                logger.info("DOM parse returned no lots on page 0")
            break

        for lot in batch:
            all_lots[lot.lot_number] = lot
        logger.info(
            "DOM page %d collected %d lots (%d total unique)",
            page,
            len(batch),
            len(all_lots),
        )

        if not _click_next_page(driver):
            break

        _wait_for_paginator_page_change(driver, before_first)
        time.sleep(config.REQUEST_DELAY_SECONDS)

    deduped = list(all_lots.values())
    logger.info("DOM pagination total: %d unique lots", len(deduped))
    return deduped


def _wait_for_paginator_page_change(driver, previous_first_lot: str | None) -> None:
    """Wait until the paginator loads a new page of results."""
    for _ in range(20):
        rows = _find_result_rows(driver)
        if not rows:
            time.sleep(0.5)
            continue
        first_lot = _extract_lot_number_from_row(rows[0])
        if not previous_first_lot or first_lot != previous_first_lot:
            time.sleep(1.5)
            return
        time.sleep(0.5)


def _first_visible_lot_number(driver) -> str | None:
    rows = _find_result_rows(driver)
    if rows:
        lot_number = _extract_lot_number_from_row(rows[0])
        return lot_number or None
    return None


def _parse_dom_lots(driver, fallback_make: str, fallback_model: str | None) -> list[Lot]:
    """Extract lots from all paginated DOM result pages."""
    return _parse_dom_lots_with_pagination(driver, fallback_make, fallback_model)


def _load_search_page(
    driver,
    url: str,
    make: str,
    model: str | None,
    min_year: int,
    max_year: int,
) -> list[Lot]:
    """Load a lotSearchResults page and extract lots via XHR + DOM parsing."""
    logger.info("Loading Copart search page for %s %s", make, model or "(all models)")
    logger.info("URL: %s", url)

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            driver.get(url)
            time.sleep(config.REQUEST_DELAY_SECONDS)
            _dismiss_cookie_banner(driver)

            if not _wait_for_results(driver):
                if attempt < config.MAX_RETRIES:
                    logger.info("Retrying page load (attempt %d)", attempt + 1)
                    time.sleep(2**attempt)
                    continue
                return []

            # Extra wait for Angular to finish binding row data.
            time.sleep(3)

            search_criteria = _search_criteria_from_url(url) or _build_search_criteria(
                make, model, min_year, max_year
            )

            # Prefer paginated XHR (up to 100 lots/page); fall back to DOM if XHR is weak.
            lots = _fetch_all_lots_via_browser_xhr(driver, search_criteria)

            if len(lots) <= 20:
                dom_lots = _parse_dom_lots_with_pagination(driver, make, model)
                if len(dom_lots) > len(lots):
                    logger.info(
                        "DOM pagination beat XHR (%d vs %d lots) — using DOM",
                        len(dom_lots),
                        len(lots),
                    )
                    lots = dom_lots

            if lots:
                logger.info(
                    "Search page for %s returned %d lots",
                    make if not model else f"{make} {model}",
                    len(lots),
                )
                return lots

            logger.info(
                "No lots found for %s on attempt %d",
                make if not model else f"{make} {model}",
                attempt,
            )
            if attempt < config.MAX_RETRIES:
                time.sleep(2**attempt)

        except Exception as exc:
            logger.error(
                "Page scrape failed for %s (attempt %d/%d): %s",
                make,
                attempt,
                config.MAX_RETRIES,
                exc,
            )
            if attempt < config.MAX_RETRIES:
                time.sleep(2**attempt)

    return []


def _dedupe_lots(lots: list[Lot]) -> list[Lot]:
    seen: set[str] = set()
    unique: list[Lot] = []
    for lot in lots:
        if lot.lot_number not in seen:
            seen.add(lot.lot_number)
            unique.append(lot)
    return unique


def scrape_lots(
    search_targets: list[tuple[str, str | None, int, int, str]] | None = None,
) -> list[Lot]:
    """
    Scrape Copart lotSearchResults pages in a real browser.

    Pass a deduped list of (make, model, min_year, max_year, url) tuples or
    leave None to use the global default watch list.
    """
    try:
        import undetected_chromedriver  # noqa: F401
    except ImportError as exc:
        logger.error(
            "Selenium dependencies missing (%s). "
            "Install with: pip install selenium undetected-chromedriver setuptools",
            exc,
        )
        return []

    targets = search_targets if search_targets is not None else _build_search_targets()
    if not targets:
        logger.warning("No search targets configured")
        return []

    all_lots: list[Lot] = []
    driver = None

    try:
        driver = _create_driver()
        for make, model, min_year, max_year, url in targets:
            lots = _load_search_page(driver, url, make, model, min_year, max_year)
            all_lots.extend(lots)
            time.sleep(config.REQUEST_DELAY_SECONDS)
    except Exception as exc:
        logger.exception("Browser scrape failed: %s", exc)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    unique = _dedupe_lots(all_lots)
    logger.info("Scrape complete — %d unique lots across %d searches", len(unique), len(targets))
    return unique
