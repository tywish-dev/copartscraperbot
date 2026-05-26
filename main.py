"""Entry point: scheduler, Telegram bot commands, and scan orchestration."""

import asyncio
import logging
import os
import threading
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import config
import db
from filters import filter_lots
from notifier import notify_new_lot
from preferences_ui import cmd_edit, handle_custom_model_message, handle_edit_callback
from scraper import build_union_search_targets, scrape_lots
from user_prefs import format_preferences_text

# --- Shared runtime state ---
last_successful_scrape: datetime | None = None
is_scheduled_scan_running = False
_active_user_scans: set[int] = set()
_active_user_scans_lock = threading.Lock()
_scan_semaphore = threading.Semaphore(config.MAX_CONCURRENT_SCANS)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def _active_user_scan_count() -> int:
    with _active_user_scans_lock:
        return len(_active_user_scans)


def format_status(user_id: int | None = None) -> str:
    """Return bot status including last scrape time."""
    if last_successful_scrape:
        scrape_time = last_successful_scrape.strftime("%Y-%m-%d %H:%M:%S UTC")
    else:
        scrape_time = "Never"

    active_users = len(db.get_active_users())
    seen_line = (
        f"• Your tracked lots: {db.get_seen_count(user_id)}\n"
        if user_id is not None
        else ""
    )
    user_scan_line = ""
    if user_id is not None:
        with _active_user_scans_lock:
            yours_running = user_id in _active_user_scans
        user_scan_line = f"• Your scan in progress: {'Yes' if yours_running else 'No'}\n"

    return (
        "📊 <b>Bot Status</b>\n\n"
        f"• Last successful scrape: {scrape_time}\n"
        f"• Active users: {active_users}\n"
        f"• Total tracked lots: {db.get_seen_count()}\n"
        f"{seen_line}"
        f"• Scheduled scan running: {'Yes' if is_scheduled_scan_running else 'No'}\n"
        f"• Manual scans running: {_active_user_scan_count()}\n"
        f"{user_scan_line}"
        f"• Check interval: {config.CHECK_INTERVAL_MINUTES} min\n"
        f"• WhatsApp enabled: {'Yes' if config.ENABLE_WHATSAPP else 'No'}"
    )


def _notify_user_matches(user: db.UserRecord, lots: list) -> dict[str, int]:
    """Filter lots for one user, send alerts, and update seen state."""
    logger = logging.getLogger(__name__)
    stats = {"filtered": 0, "notified": 0, "skipped": 0}
    matched = filter_lots(lots, user.prefs)
    stats["filtered"] = len(matched)

    for lot in matched:
        if db.is_lot_seen(user.telegram_user_id, lot.lot_number):
            stats["skipped"] += 1
            continue

        if notify_new_lot(lot, chat_id=user.chat_id):
            db.mark_lot_seen(user.telegram_user_id, lot.lot_number)
            stats["notified"] += 1
        else:
            logger.warning(
                "Notification failed for lot %s user %s",
                lot.lot_number,
                user.telegram_user_id,
            )

    return stats


def _scrape_targets(targets: list) -> list:
    """Run a browser scrape, respecting the global concurrent scan limit."""
    _scan_semaphore.acquire()
    try:
        return scrape_lots(targets)
    finally:
        _scan_semaphore.release()


def run_scan_all_users() -> dict[str, int]:
    """
    Scheduled scan: scrape the union of all users' watch lists once,
    then filter and notify each user independently.
    """
    global last_successful_scrape, is_scheduled_scan_running

    if is_scheduled_scan_running:
        logging.getLogger(__name__).warning("Scheduled scan already in progress, skipping")
        return {"found": 0, "filtered": 0, "notified": 0, "skipped": 0}

    is_scheduled_scan_running = True
    logger = logging.getLogger(__name__)
    stats = {"found": 0, "filtered": 0, "notified": 0, "skipped": 0}

    try:
        users = db.get_active_users()
        if not users:
            logger.info("No active users registered — skipping scan")
            return stats

        logger.info("Starting scheduled Copart scan for %d user(s)", len(users))
        union_targets = build_union_search_targets([u.prefs for u in users])
        lots = _scrape_targets(union_targets)
        stats["found"] = len(lots)

        if lots:
            last_successful_scrape = datetime.now(timezone.utc)

        for user in users:
            user_stats = _notify_user_matches(user, lots)
            stats["filtered"] += user_stats["filtered"]
            stats["notified"] += user_stats["notified"]
            stats["skipped"] += user_stats["skipped"]

        logger.info(
            "Scheduled scan complete — found=%d filtered=%d notified=%d skipped=%d",
            stats["found"],
            stats["filtered"],
            stats["notified"],
            stats["skipped"],
        )
    except Exception as exc:
        logger.exception("Scheduled scan failed with unexpected error: %s", exc)
    finally:
        is_scheduled_scan_running = False

    return stats


def run_scan_for_user(telegram_user_id: int) -> dict[str, int | str | None]:
    """
    Manual /check scan for a single user only.

    Scrapes that user's watch list, notifies only that user, and can run
    concurrently with other users' /check commands (up to MAX_CONCURRENT_SCANS).
    """
    global last_successful_scrape

    logger = logging.getLogger(__name__)
    stats: dict[str, int | str | None] = {
        "found": 0,
        "filtered": 0,
        "notified": 0,
        "skipped": 0,
        "error": None,
    }

    with _active_user_scans_lock:
        if telegram_user_id in _active_user_scans:
            stats["error"] = "already_running"
            return stats
        _active_user_scans.add(telegram_user_id)

    try:
        user = db.get_user_record(telegram_user_id)
        if user is None:
            stats["error"] = "not_found"
            return stats

        if not user.prefs.search_targets:
            stats["error"] = "empty_watchlist"
            return stats

        logger.info("Starting manual scan for user %d", telegram_user_id)
        targets = build_union_search_targets([user.prefs])
        lots = _scrape_targets(targets)
        stats["found"] = len(lots)

        if lots:
            last_successful_scrape = datetime.now(timezone.utc)

        user_stats = _notify_user_matches(user, lots)
        stats["filtered"] = user_stats["filtered"]
        stats["notified"] = user_stats["notified"]
        stats["skipped"] = user_stats["skipped"]

        logger.info(
            "Manual scan complete for user %d — found=%d filtered=%d notified=%d skipped=%d",
            telegram_user_id,
            stats["found"],
            stats["filtered"],
            stats["notified"],
            stats["skipped"],
        )
    except Exception as exc:
        logger.exception("Manual scan failed for user %d: %s", telegram_user_id, exc)
        stats["error"] = "failed"
    finally:
        with _active_user_scans_lock:
            _active_user_scans.discard(telegram_user_id)

    return stats


def _register_user(update: Update) -> db.UserRecord:
    user = update.effective_user
    chat = update.effective_chat
    return db.get_or_create_user(
        telegram_user_id=user.id,
        chat_id=chat.id,
        username=user.username,
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _register_user(update)
    await update.message.reply_text(
        "👋 <b>Copart Monitor Bot</b>\n\n"
        "I watch Copart for vehicles matching <b>your</b> preferences "
        "and send alerts here automatically.\n\n"
        "Commands:\n"
        "/start — Show this message\n"
        "/preferences — View your filter settings\n"
        "/edit — Edit your preferences (inline menus)\n"
        "/check — Scan <b>your</b> watch list now\n"
        "/status — View bot status and your stats",
        parse_mode="HTML",
    )


async def cmd_preferences(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    record = _register_user(update)
    await update.message.reply_text(
        format_preferences_text(record.prefs),
        parse_mode="HTML",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _register_user(update)
    await update.message.reply_text(
        format_status(update.effective_user.id),
        parse_mode="HTML",
    )


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    record = _register_user(update)
    user_id = record.telegram_user_id

    with _active_user_scans_lock:
        if user_id in _active_user_scans:
            await update.message.reply_text(
                "⏳ You already have a scan running. Wait for it to finish, then try again.",
            )
            return

    await update.message.reply_text(
        "🔍 Starting a scan for <b>your</b> watch list only…",
        parse_mode="HTML",
    )

    stats = await asyncio.to_thread(run_scan_for_user, user_id)

    error = stats.get("error")
    if error == "already_running":
        await update.message.reply_text(
            "⏳ You already have a scan running. Wait for it to finish, then try again.",
        )
        return
    if error == "empty_watchlist":
        await update.message.reply_text(
            "⚠️ Your watch list is empty. Use /edit to add vehicles first.",
        )
        return
    if error == "not_found":
        await update.message.reply_text("⚠️ User not found. Send /start to register.")
        return
    if error == "failed":
        await update.message.reply_text("❌ Scan failed. Check bot.log for details.")
        return

    await update.message.reply_text(
        f"✅ Scan finished\n\n"
        f"• Found: {stats['found']}\n"
        f"• Matched your filters: {stats['filtered']}\n"
        f"• New alerts sent to you: {stats['notified']}\n"
        f"• Already seen by you: {stats['skipped']}",
        parse_mode="HTML",
    )


def scheduled_scan() -> None:
    """Background job invoked by APScheduler."""
    run_scan_all_users()


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is required. Copy .env.example to .env and fill it in.")
        raise SystemExit(1)

    db.init_db()
    db.seed_admin_user_if_configured()
    config.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Database initialized at %s", config.DATABASE_PATH)

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        scheduled_scan,
        "interval",
        minutes=config.CHECK_INTERVAL_MINUTES,
        id="copart_scan",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler started — scanning every %d minutes",
        config.CHECK_INTERVAL_MINUTES,
    )

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("preferences", cmd_preferences))
    app.add_handler(CommandHandler("edit", cmd_edit))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CallbackQueryHandler(handle_edit_callback, pattern=r"^edit:"))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_model_message)
    )

    logger.info("Running initial scheduled scan on startup")
    skip_initial = os.getenv("SKIP_INITIAL_SCAN", "").lower() in ("true", "1", "yes")
    if skip_initial:
        logger.info("SKIP_INITIAL_SCAN is set — skipping startup scan")
    else:
        initial_stats = run_scan_all_users()
        logger.info(
            "Initial scan — found=%d filtered=%d notified=%d",
            initial_stats["found"],
            initial_stats["filtered"],
            initial_stats["notified"],
        )

    logger.info("Telegram bot polling started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
