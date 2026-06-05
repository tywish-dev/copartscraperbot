"""Per-user preference model with JSON serialization."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any

import config

MAX_WATCH_LIST_ENTRIES = 20

DAMAGE_OPTIONS: list[dict[str, str]] = [
    {"code": "DAMAGECODE_FR", "keyword": "FRONT END", "label": "Front End"},
    {"code": "DAMAGECODE_MN", "keyword": "MINOR DENT", "label": "Minor Dent/Scratches"},
    {"code": "DAMAGECODE_NW", "keyword": "NORMAL WEAR", "label": "Normal Wear"},
    {"code": "DAMAGECODE_RR", "keyword": "REAR END", "label": "Rear End"},
    {"code": "DAMAGECODE_SD", "keyword": "SIDE", "label": "Side"},
    {"code": "DAMAGECODE_UN", "keyword": "UNKNOWN", "label": "Unknown"},
    {"code": "DAMAGECODE_VN", "keyword": "VANDALISM", "label": "Vandalism"},
]

POPULAR_MAKES = [
    "BMW",
    "Porsche",
    "Chevrolet",
    "Tesla",
    "Mercedes",
    "Audi",
    "Toyota",
    "Ford",
    "Honda",
    "Nissan",
]


@dataclass
class SearchTarget:
    make: str
    models: list[str] = field(default_factory=list)
    min_year: int = 2010
    max_year: int = config.MAX_YEAR
    all_models: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SearchTarget:
        return cls(
            make=str(data["make"]),
            models=list(data.get("models") or []),
            min_year=int(data.get("min_year", 2010)),
            max_year=int(data.get("max_year", config.MAX_YEAR)),
            all_models=bool(data.get("all_models", False)),
        )

    def label(self) -> str:
        if self.all_models or not self.models:
            models_str = "all models"
        else:
            models_str = ", ".join(self.models)
        return f"{self.make} ({models_str}) {self.min_year}–{self.max_year}"


@dataclass
class UserPreferences:
    search_targets: list[SearchTarget] = field(default_factory=list)
    require_clean_title: bool = True
    only_buy_now: bool = False
    max_odometer: int = 999_999
    allowed_damage_keywords: list[str] = field(default_factory=list)
    preferred_locations: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        payload = {
            "search_targets": [t.to_dict() for t in self.search_targets],
            "require_clean_title": self.require_clean_title,
            "only_buy_now": self.only_buy_now,
            "max_odometer": self.max_odometer,
            "allowed_damage_keywords": self.allowed_damage_keywords,
            "preferred_locations": self.preferred_locations,
        }
        return json.dumps(payload)

    @classmethod
    def from_json(cls, raw: str) -> UserPreferences:
        data = json.loads(raw)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserPreferences:
        targets = [
            SearchTarget.from_dict(t) for t in data.get("search_targets", [])
        ]
        keywords = list(data.get("allowed_damage_keywords") or default_damage_keywords())
        return cls(
            search_targets=targets,
            require_clean_title=bool(data.get("require_clean_title", True)),
            only_buy_now=bool(data.get("only_buy_now", False)),
            max_odometer=int(data.get("max_odometer", 999_999)),
            allowed_damage_keywords=keywords,
            preferred_locations=list(data.get("preferred_locations") or []),
        )

    def allowed_damage_codes(self) -> list[str]:
        codes: list[str] = []
        for option in DAMAGE_OPTIONS:
            if option["keyword"] in self.allowed_damage_keywords:
                codes.append(option["code"])
        return codes


def default_damage_keywords() -> list[str]:
    return list(config.ALLOWED_DAMAGE_KEYWORDS)


def default_search_targets() -> list[SearchTarget]:
    return [
        SearchTarget.from_dict(dict(t)) for t in config.DEFAULT_SEARCH_TARGETS
    ]


def default_preferences() -> UserPreferences:
    return UserPreferences(
        search_targets=default_search_targets(),
        require_clean_title=True,
        only_buy_now=False,
        max_odometer=999_999,
        allowed_damage_keywords=default_damage_keywords(),
        preferred_locations=[],
    )


def format_preferences_text(prefs: UserPreferences) -> str:
    if prefs.search_targets:
        watch_lines = "".join(
            f"\n• {target.label()}" for target in prefs.search_targets
        )
    else:
        watch_lines = "\n• (empty — use /edit to add vehicles)"

    damage_labels = ", ".join(
        opt["label"]
        for opt in DAMAGE_OPTIONS
        if opt["keyword"] in prefs.allowed_damage_keywords
    ) or "None"

    locations = (
        ", ".join(prefs.preferred_locations) if prefs.preferred_locations else "Nationwide"
    )

    return (
        "⚙️ <b>Your Preferences</b>\n\n"
        f"<b>Watch list:</b>{watch_lines}\n\n"
        f"• Title: {'Clean title only' if prefs.require_clean_title else 'Any title'}\n"
        f"• Buy now only: {'Yes' if prefs.only_buy_now else 'No (auctions included)'}\n"
        f"• Allowed damage: {damage_labels}\n"
        f"• Max odometer: {prefs.max_odometer:,} mi\n"
        f"• States: {locations}\n"
        f"• Check interval: {config.CHECK_INTERVAL_MINUTES} min (automatic)"
    )


def iter_scrape_entries(prefs: UserPreferences) -> list[tuple[str, str | None, int, int]]:
    """Expand user watch list into (make, model, min_year, max_year) scrape tuples."""
    entries: list[tuple[str, str | None, int, int]] = []
    for target in prefs.search_targets:
        if target.all_models or not target.models:
            entries.append((target.make, None, target.min_year, target.max_year))
        else:
            for model in target.models:
                entries.append((target.make, model, target.min_year, target.max_year))
    return entries
