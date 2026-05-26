"""Entry point: scheduler, Telegram bot commands, and scan orchestration."""

import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import config
import db
from filters import filter_lots
from notifier import notify_new_lot, send_telegram_text_async
from scraper import scrape_lots

# --- Shared runtime state ---
last_successful_scrape: datetime | None = None
is_scan_running = False


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def format_preferences() -> str:
    """Return current filter settings as a readable string."""
    return (
        "⚙️ <b>Current Preferences</b>\n\n"
        f"• Makes: {', '.join(config.PREFERRED_MAKES)}\n"
        f"• Min year: {config.MIN_YEAR}\n"
        f"• Max odometer: {config.MAX_ODOMETER:,} mi\n"
        f"• Max buy now: ${config.MAX_BUY_NOW_PRICE:,}\n"
        f"• Buy now only: {'Yes' if config.ONLY_BUY_NOW else 'No'}\n"
        f"• Excluded damage: {', '.join(config.EXCLUDED_DAMAGE)}\n"
        f"• Preferred states: {', '.join(config.PREFERRED_LOCATIONS)}\n"
        f"• Check interval: {config.CHECK_INTERVAL_MINUTES} min"
    )


def format_status() -> str:
    """Return bot status including last scrape time."""
    if last_successful_scrape:
        scrape_time = last_successful_scrape.strftime("%Y-%m-%d %H:%M:%S UTC")
    else:
        scrape_time = "Never"

    return (
        "📊 <b>Bot Status</b>\n\n"
        f"• Last successful scrape: {scrape_time}\n"
        f"• Lots tracked (seen): {db.get_seen_count()}\n"
        f"• Scan in progress: {'Yes' if is_scan_running else 'No'}\n"
        f"• Check interval: {config.CHECK_INTERVAL_MINUTES} min\n"
        f"• WhatsApp enabled: {'Yes' if config.ENABLE_WHATSAPP else 'No'}"
    )


def run_scan() -> dict[str, int]:
    """
    Execute a full scrape-filter-notify cycle.

    Returns counts: found, filtered, notified, skipped.
    """
    global last_successful_scrape, is_scan_running

    if is_scan_running:
        logging.getLogger(__name__).warning("Scan already in progress, skipping")
        return {"found": 0, "filtered": 0, "notified": 0, "skipped": 0}

    is_scan_running = True
    logger = logging.getLogger(__name__)
    stats = {"found": 0, "filtered": 0, "notified": 0, "skipped": 0}

    try:
        logger.info("Starting Copart scan")
        lots = scrape_lots()
        stats["found"] = len(lots)

        if lots:
            last_successful_scrape = datetime.now(timezone.utc)

        matched = filter_lots(lots)
        stats["filtered"] = len(matched)

        for lot in matched:
            if db.is_lot_seen(lot.lot_number):
                stats["skipped"] += 1
                continue

            if notify_new_lot(lot):
                db.mark_lot_seen(lot.lot_number)
                stats["notified"] += 1
            else:
                logger.warning(
                    "Notification failed for lot %s; not marking as seen",
                    lot.lot_number,
                )

        logger.info(
            "Scan complete — found=%d filtered=%d notified=%d skipped=%d",
            stats["found"],
            stats["filtered"],
            stats["notified"],
            stats["skipped"],
        )
    except Exception as exc:
        logger.exception("Scan failed with unexpected error: %s", exc)
    finally:
        is_scan_running = False

    return stats


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 <b>Copart Monitor Bot</b>\n\n"
        "I watch Copart for vehicles matching your preferences and send alerts here.\n\n"
        "Commands:\n"
        "/start — Show this message\n"
        "/preferences — View current filter settings\n"
        "/check — Run an immediate scan\n"
        "/status — View bot status and last scrape time",
        parse_mode="HTML",
    )


async def cmd_preferences(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(format_preferences(), parse_mode="HTML")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(format_status(), parse_mode="HTML")


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔍 Starting immediate scan…")

    stats = await asyncio.to_thread(run_scan)

    await update.message.reply_text(
        f"✅ Scan finished\n\n"
        f"• Found: {stats['found']}\n"
        f"• Matched filters: {stats['filtered']}\n"
        f"• New alerts sent: {stats['notified']}\n"
        f"• Already seen: {stats['skipped']}",
        parse_mode="HTML",
    )


def scheduled_scan() -> None:
    """Background job invoked by APScheduler."""
    stats = run_scan()
    if stats["notified"] > 0:
        asyncio.run(
            send_telegram_text_async(
                f"🔔 Scheduled scan sent <b>{stats['notified']}</b> new alert(s)."
            )
        )


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.error(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required. "
            "Copy .env.example to .env and fill them in."
        )
        raise SystemExit(1)

    db.init_db()
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

    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("preferences", cmd_preferences))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("status", cmd_status))

    logger.info("Running initial scan on startup")
    initial_stats = run_scan()
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
