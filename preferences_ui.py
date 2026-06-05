"""Inline keyboard UI for /edit preferences."""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db
from user_prefs import (
    DAMAGE_OPTIONS,
    MAX_WATCH_LIST_ENTRIES,
    POPULAR_MAKES,
    SearchTarget,
    UserPreferences,
    default_preferences,
    format_preferences_text,
)

logger = logging.getLogger(__name__)

# user_data keys
PENDING_MAKE = "pending_make"
PENDING_MODELS = "pending_models"
PENDING_ALL_MODELS = "pending_all_models"
PENDING_MIN_YEAR = "pending_min_year"
AWAIT_CUSTOM_MODEL = "await_custom_model"


def _user_id(update: Update) -> int:
    return update.effective_user.id


def _load_prefs(update: Update) -> UserPreferences:
    return db.get_user_preferences(_user_id(update))


def _save_prefs(update: Update, prefs: UserPreferences) -> None:
    db.save_user_preferences(_user_id(update), prefs)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Watch List", callback_data="edit:watch")],
            [InlineKeyboardButton("Damage Types", callback_data="edit:damage")],
            [InlineKeyboardButton("Title & Odometer", callback_data="edit:title")],
            [InlineKeyboardButton("Reset to Defaults", callback_data="edit:reset")],
            [InlineKeyboardButton("Done", callback_data="edit:done")],
        ]
    )


def watch_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Add Vehicle", callback_data="edit:watch:add")],
            [InlineKeyboardButton("Remove Vehicle", callback_data="edit:watch:remove")],
            [InlineKeyboardButton("Back", callback_data="edit:main")],
        ]
    )


def make_keyboard() -> InlineKeyboardMarkup:
    rows = []
    row: list[InlineKeyboardButton] = []
    for make in POPULAR_MAKES:
        row.append(InlineKeyboardButton(make, callback_data=f"edit:watch:make:{make}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("Back", callback_data="edit:watch")])
    return InlineKeyboardMarkup(rows)


def model_keyboard(make: str) -> InlineKeyboardMarkup:
    suggestions: dict[str, list[str]] = {
        "BMW": ["M3", "M4", "M5", "X5"],
        "Porsche": ["911", "Cayman", "Cayenne", "Macan"],
        "Chevrolet": ["Corvette", "Camaro"],
        "Tesla": ["Model S", "Model 3", "Model Y", "Model X"],
    }
    models = suggestions.get(make, [])
    rows = [[InlineKeyboardButton("All Models", callback_data="edit:watch:allmodels")]]
    row: list[InlineKeyboardButton] = []
    for model in models:
        row.append(
            InlineKeyboardButton(model, callback_data=f"edit:watch:model:{model}")
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("Type Custom Model", callback_data="edit:watch:custom")])
    rows.append([InlineKeyboardButton("Back", callback_data="edit:watch:add")])
    return InlineKeyboardMarkup(rows)


def year_keyboard(prefix: str) -> InlineKeyboardMarkup:
    years = ["2010", "2015", "2017", "2020", "2022", "2025", "2027"]
    rows = []
    row: list[InlineKeyboardButton] = []
    for year in years:
        row.append(
            InlineKeyboardButton(year, callback_data=f"edit:watch:{prefix}:{year}")
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("Back", callback_data="edit:watch")])
    return InlineKeyboardMarkup(rows)


def damage_keyboard(prefs: UserPreferences) -> InlineKeyboardMarkup:
    rows = []
    for opt in DAMAGE_OPTIONS:
        enabled = opt["keyword"] in prefs.allowed_damage_keywords
        icon = "✅" if enabled else "❌"
        code = opt["code"].replace("DAMAGECODE_", "")
        rows.append(
            [
                InlineKeyboardButton(
                    f"{icon} {opt['label']}",
                    callback_data=f"edit:dmg:{code}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("Back", callback_data="edit:main")])
    return InlineKeyboardMarkup(rows)


def title_keyboard(prefs: UserPreferences) -> InlineKeyboardMarkup:
    clean_icon = "✅" if prefs.require_clean_title else "❌"
    buy_icon = "✅" if prefs.only_buy_now else "❌"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"{clean_icon} Clean Title Required",
                    callback_data="edit:tgl:clean",
                )
            ],
            [
                InlineKeyboardButton(
                    f"{buy_icon} Buy Now Only",
                    callback_data="edit:tgl:buynow",
                )
            ],
            [
                InlineKeyboardButton("Max Odometer: 120k", callback_data="edit:odo:120000"),
                InlineKeyboardButton("Max Odometer: 999k", callback_data="edit:odo:999999"),
            ],
            [InlineKeyboardButton("Back", callback_data="edit:main")],
        ]
    )


def remove_keyboard(prefs: UserPreferences) -> InlineKeyboardMarkup:
    rows = []
    for idx, target in enumerate(prefs.search_targets):
        label = target.label()[:40]
        rows.append(
            [InlineKeyboardButton(f"Remove {label}", callback_data=f"edit:watch:del:{idx}")]
        )
    if not rows:
        rows.append([InlineKeyboardButton("(empty)", callback_data="edit:watch")])
    rows.append([InlineKeyboardButton("Back", callback_data="edit:watch")])
    return InlineKeyboardMarkup(rows)


async def cmd_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prefs = _load_prefs(update)
    text = format_preferences_text(prefs)
    text += "\n\nUse the buttons below to edit:"
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


async def handle_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    data = query.data
    prefs = _load_prefs(update)
    user_data = context.user_data

    if data == "edit:main":
        user_data.pop(AWAIT_CUSTOM_MODEL, None)
        await query.edit_message_text(
            format_preferences_text(prefs) + "\n\nUse the buttons below to edit:",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return

    if data == "edit:done":
        user_data.pop(AWAIT_CUSTOM_MODEL, None)
        await query.edit_message_text(
            format_preferences_text(prefs) + "\n\n✅ Preferences saved.",
            parse_mode="HTML",
        )
        return

    if data == "edit:reset":
        prefs = default_preferences()
        _save_prefs(update, prefs)
        await query.edit_message_text(
            format_preferences_text(prefs) + "\n\n↩️ Reset to defaults.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return

    if data == "edit:watch":
        user_data.pop(AWAIT_CUSTOM_MODEL, None)
        summary = "\n".join(f"• {t.label()}" for t in prefs.search_targets) or "(empty)"
        await query.edit_message_text(
            f"<b>Watch List</b>\n{summary}",
            parse_mode="HTML",
            reply_markup=watch_menu_keyboard(),
        )
        return

    if data == "edit:watch:add":
        if len(prefs.search_targets) >= MAX_WATCH_LIST_ENTRIES:
            await query.answer("Watch list limit reached.", show_alert=True)
            return
        user_data.pop(PENDING_MAKE, None)
        user_data.pop(PENDING_MODELS, None)
        user_data.pop(PENDING_ALL_MODELS, None)
        user_data.pop(PENDING_MIN_YEAR, None)
        await query.edit_message_text(
            "Select a make:",
            reply_markup=make_keyboard(),
        )
        return

    if data.startswith("edit:watch:make:"):
        make = data.split(":", 3)[3]
        user_data[PENDING_MAKE] = make
        user_data[PENDING_MODELS] = []
        user_data[PENDING_ALL_MODELS] = False
        await query.edit_message_text(
            f"Selected <b>{make}</b>. Choose model(s) or All Models:",
            parse_mode="HTML",
            reply_markup=model_keyboard(make),
        )
        return

    if data == "edit:watch:allmodels":
        user_data[PENDING_ALL_MODELS] = True
        user_data[PENDING_MODELS] = []
        await query.edit_message_text(
            "Select minimum year:",
            reply_markup=year_keyboard("min"),
        )
        return

    if data.startswith("edit:watch:model:"):
        model = data.split(":", 3)[3]
        user_data[PENDING_MODELS] = [model]
        user_data[PENDING_ALL_MODELS] = False
        await query.edit_message_text(
            f"Model: <b>{model}</b>. Select minimum year:",
            parse_mode="HTML",
            reply_markup=year_keyboard("min"),
        )
        return

    if data == "edit:watch:custom":
        user_data[AWAIT_CUSTOM_MODEL] = True
        await query.edit_message_text(
            "Send the model name as a message (e.g. <code>M3</code> or <code>911 Carrera</code>).",
            parse_mode="HTML",
        )
        return

    if data.startswith("edit:watch:min:"):
        min_year = int(data.split(":")[3])
        user_data[PENDING_MIN_YEAR] = min_year
        await query.edit_message_text(
            f"Min year: <b>{min_year}</b>. Select maximum year:",
            parse_mode="HTML",
            reply_markup=year_keyboard("max"),
        )
        return

    if data.startswith("edit:watch:max:"):
        max_year = int(data.split(":")[3])
        min_year = int(user_data.get(PENDING_MIN_YEAR, 2010))
        make = str(user_data.get(PENDING_MAKE, ""))
        all_models = bool(user_data.get(PENDING_ALL_MODELS, False))
        models = list(user_data.get(PENDING_MODELS, []))

        if not make:
            await query.answer("Missing make — start again.", show_alert=True)
            return

        prefs.search_targets.append(
            SearchTarget(
                make=make,
                models=models,
                min_year=min_year,
                max_year=max_year,
                all_models=all_models,
            )
        )
        _save_prefs(update, prefs)
        user_data.pop(PENDING_MAKE, None)
        user_data.pop(PENDING_MODELS, None)
        user_data.pop(PENDING_ALL_MODELS, None)
        user_data.pop(PENDING_MIN_YEAR, None)

        await query.edit_message_text(
            f"Added: <b>{prefs.search_targets[-1].label()}</b>",
            parse_mode="HTML",
            reply_markup=watch_menu_keyboard(),
        )
        return

    if data == "edit:watch:remove":
        await query.edit_message_text(
            "Select a vehicle to remove:",
            reply_markup=remove_keyboard(prefs),
        )
        return

    if data.startswith("edit:watch:del:"):
        idx = int(data.split(":")[3])
        if 0 <= idx < len(prefs.search_targets):
            removed = prefs.search_targets.pop(idx)
            _save_prefs(update, prefs)
            await query.edit_message_text(
                f"Removed: <b>{removed.label()}</b>",
                parse_mode="HTML",
                reply_markup=watch_menu_keyboard(),
            )
        return

    if data == "edit:damage":
        await query.edit_message_text(
            "Toggle allowed damage types:",
            reply_markup=damage_keyboard(prefs),
        )
        return

    if data.startswith("edit:dmg:"):
        code_suffix = data.split(":")[2]
        option = next(
            (
                opt
                for opt in DAMAGE_OPTIONS
                if opt["code"] == f"DAMAGECODE_{code_suffix}"
            ),
            None,
        )
        if option:
            keyword = option["keyword"]
            if keyword in prefs.allowed_damage_keywords:
                prefs.allowed_damage_keywords.remove(keyword)
            else:
                prefs.allowed_damage_keywords.append(keyword)
            _save_prefs(update, prefs)
        await query.edit_message_text(
            "Toggle allowed damage types:",
            reply_markup=damage_keyboard(prefs),
        )
        return

    if data == "edit:title":
        await query.edit_message_text(
            "Title and odometer settings:",
            reply_markup=title_keyboard(prefs),
        )
        return

    if data == "edit:tgl:clean":
        prefs.require_clean_title = not prefs.require_clean_title
        _save_prefs(update, prefs)
        await query.edit_message_text(
            "Title and odometer settings:",
            reply_markup=title_keyboard(prefs),
        )
        return

    if data == "edit:tgl:buynow":
        prefs.only_buy_now = not prefs.only_buy_now
        _save_prefs(update, prefs)
        await query.edit_message_text(
            "Title and odometer settings:",
            reply_markup=title_keyboard(prefs),
        )
        return

    if data.startswith("edit:odo:"):
        prefs.max_odometer = int(data.split(":")[2])
        _save_prefs(update, prefs)
        await query.edit_message_text(
            "Title and odometer settings:",
            reply_markup=title_keyboard(prefs),
        )
        return


async def handle_custom_model_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not context.user_data.get(AWAIT_CUSTOM_MODEL):
        return

    if not update.message or not update.message.text:
        return

    model = update.message.text.strip()
    if not model:
        await update.message.reply_text("Please send a valid model name.")
        return

    context.user_data[PENDING_MODELS] = [model]
    context.user_data[PENDING_ALL_MODELS] = False
    context.user_data.pop(AWAIT_CUSTOM_MODEL, None)

    await update.message.reply_text(
        f"Model: <b>{model}</b>. Select minimum year:",
        parse_mode="HTML",
        reply_markup=year_keyboard("min"),
    )
