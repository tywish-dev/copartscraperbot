"""Car preference filtering logic for Copart lot results."""

import logging
import re
from dataclasses import dataclass

from user_prefs import SearchTarget, UserPreferences

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
    title_status: str = ""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().upper())


def _parse_odometer(value: int | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    cleaned = re.sub(r"[^\d]", "", str(value))
    return int(cleaned) if cleaned else None


def _parse_price(value: float | int | str | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d.]", "", str(value))
    return float(cleaned) if cleaned else None


def _model_matches(lot: Lot, models: list[str], all_models: bool) -> bool:
    if all_models:
        return True
    haystack = _normalize(f"{lot.model} {lot.title}")
    return any(_normalize(model) in haystack for model in models)


def _make_matches(lot: Lot, target_make: str) -> bool:
    target = _normalize(target_make).replace(" ", "")
    haystack = _normalize(f"{lot.make} {lot.title}").replace(" ", "")
    return target in haystack


def _find_search_target(lot: Lot, targets: list[SearchTarget]) -> SearchTarget | None:
    for target in targets:
        if not _make_matches(lot, target.make):
            continue

        if not _model_matches(lot, target.models, target.all_models):
            continue

        if lot.year is not None:
            if lot.year < target.min_year or lot.year > target.max_year:
                continue

        return target
    return None


def _has_clean_title(lot: Lot) -> bool:
    blob = _normalize(f"{lot.title_status} {lot.title}")
    return "CLEAN TITLE" in blob or "CLEAN-TITLE" in blob


def _damage_allowed(damage: str, allowed_keywords: list[str]) -> bool:
    normalized = _normalize(damage)
    return any(keyword in normalized for keyword in allowed_keywords)


def lot_matches_preferences(lot: Lot, prefs: UserPreferences) -> bool:
    """Return True if the lot passes the given user's filters."""
    if not prefs.search_targets:
        return False

    target = _find_search_target(lot, prefs.search_targets)
    if target is None:
        return False

    if prefs.require_clean_title and not _has_clean_title(lot):
        return False

    odometer = _parse_odometer(lot.odometer)
    if odometer is not None and odometer > prefs.max_odometer:
        return False

    buy_now = _parse_price(lot.buy_now_price)
    if prefs.only_buy_now and (buy_now is None or buy_now <= 0):
        return False

    if not _damage_allowed(lot.damage_type, prefs.allowed_damage_keywords):
        return False

    if prefs.preferred_locations:
        match = re.search(r"\b([A-Z]{2})\b", _normalize(lot.location))
        state = match.group(1) if match else None
        preferred = {_normalize(s) for s in prefs.preferred_locations}
        if state and state not in preferred:
            return False

    return True


def filter_lots(lots: list[Lot], prefs: UserPreferences) -> list[Lot]:
    """Filter lots against a single user's preferences."""
    matched = [lot for lot in lots if lot_matches_preferences(lot, prefs)]
    logger.info(
        "Filtered %d lots down to %d for user watch list",
        len(lots),
        len(matched),
    )
    return matched
