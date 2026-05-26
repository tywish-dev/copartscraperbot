"""Car preference filtering logic for Copart lot results."""

import logging
import re
from dataclasses import dataclass

import config

logger = logging.getLogger(__name__)


@dataclass
class Lot:
    lot_number: str
    title: str
    year: int | None
    make: str
    model: str
    odometer: int | None
    damage_type: str
    estimated_repair_cost: float | None
    buy_now_price: float | None
    auction_date: str
    location: str
    images: list[str]
    lot_url: str


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().upper())


def _extract_state(location: str) -> str | None:
    """Extract US state code from a location string like 'DALLAS TX'."""
    match = re.search(r"\b([A-Z]{2})\b", _normalize(location))
    return match.group(1) if match else None


def _parse_price(value: float | int | str | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d.]", "", str(value))
    return float(cleaned) if cleaned else None


def _parse_odometer(value: int | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    cleaned = re.sub(r"[^\d]", "", str(value))
    return int(cleaned) if cleaned else None


def lot_matches_preferences(lot: Lot) -> bool:
    """Return True if the lot passes all active user filters."""
    make = _normalize(lot.make)

    if config.PREFERRED_MAKES:
        preferred = {_normalize(m) for m in config.PREFERRED_MAKES}
        if make not in preferred:
            return False

    if lot.year is not None and lot.year < config.MIN_YEAR:
        return False

    odometer = _parse_odometer(lot.odometer)
    if odometer is not None and odometer > config.MAX_ODOMETER:
        return False

    buy_now = _parse_price(lot.buy_now_price)
    if config.ONLY_BUY_NOW and (buy_now is None or buy_now <= 0):
        return False

    if buy_now is not None and buy_now > config.MAX_BUY_NOW_PRICE:
        return False

    damage = _normalize(lot.damage_type)
    for excluded in config.EXCLUDED_DAMAGE:
        if _normalize(excluded) in damage:
            return False

    if config.PREFERRED_LOCATIONS:
        state = _extract_state(lot.location)
        preferred_states = {_normalize(s) for s in config.PREFERRED_LOCATIONS}
        if state and state not in preferred_states:
            return False

    return True


def filter_lots(lots: list[Lot]) -> list[Lot]:
    """Filter a list of lots, returning only those matching preferences."""
    matched = [lot for lot in lots if lot_matches_preferences(lot)]
    logger.info(
        "Filtered %d lots down to %d matching preferences",
        len(lots),
        len(matched),
    )
    return matched
