"""Telegram and optional WhatsApp notification delivery."""

import asyncio
import logging

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

import config
from filters import Lot

logger = logging.getLogger(__name__)


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_lot_message_markdown(lot: Lot) -> str:
    """Build a Telegram-friendly HTML message for a lot."""
    year = lot.year or "?"
    make = _escape_html(lot.make or "Unknown")
    model = _escape_html(lot.model or "")
    title = _escape_html(f"{year} {make} {model}")
    odometer = (
        f"{lot.odometer:,} mi"
        if lot.odometer is not None
        else "Unknown"
    )
    location = _escape_html(lot.location)
    damage = _escape_html(lot.damage_type)
    title_status = _escape_html(lot.title_status or "Unknown")
    auction = _escape_html(lot.auction_date)
    lot_url = _escape_html(lot.lot_url)

    price_line = (
        f"💰 Buy Now: ${lot.buy_now_price:,.0f}\n"
        if lot.buy_now_price
        else "💰 Price: Auction\n"
    )

    return (
        f"🚗 <b>{title}</b>\n"
        f"📄 Title: {title_status}\n"
        f"{price_line}"
        f"📍 Location: {location}\n"
        f"🔧 Damage: {damage}\n"
        f"🛣 Odometer: {odometer}\n"
        f"📅 Auction: {auction}\n"
        f'🔗 <a href="{lot_url}">View Lot</a>'
    )


def format_lot_message_plain(lot: Lot) -> str:
    """Build a plain-text message for WhatsApp."""
    year = lot.year or "?"
    make = lot.make or "Unknown"
    model = lot.model or ""
    buy_now = (
        f"${lot.buy_now_price:,.0f}"
        if lot.buy_now_price
        else "N/A"
    )
    odometer = (
        f"{lot.odometer:,} mi"
        if lot.odometer is not None
        else "Unknown"
    )

    return (
        f"🚗 {year} {make} {model}\n"
        f"💰 Buy Now: {buy_now}\n"
        f"📍 Location: {lot.location}\n"
        f"🔧 Damage: {lot.damage_type}\n"
        f"🛣 Odometer: {odometer}\n"
        f"📅 Auction: {lot.auction_date}\n"
        f"🔗 {lot.lot_url}"
    )


async def _send_telegram_async(lot: Lot, chat_id: str | int) -> bool:
    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("Telegram bot token not configured")
        return False

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    message = format_lot_message_markdown(lot)

    for attempt in (1, 2):
        try:
            if lot.images:
                await bot.send_photo(
                    chat_id=str(chat_id),
                    photo=lot.images[0],
                    caption=message,
                    parse_mode=ParseMode.HTML,
                )
            else:
                await bot.send_message(
                    chat_id=str(chat_id),
                    text=message,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=False,
                )
            logger.info("Telegram alert sent for lot %s to chat %s", lot.lot_number, chat_id)
            return True
        except TelegramError as exc:
            logger.error(
                "Telegram send failed for lot %s to chat %s (attempt %d): %s",
                lot.lot_number,
                chat_id,
                attempt,
                exc,
            )
            if attempt == 1:
                await asyncio.sleep(60)
            else:
                return False
    return False


def send_telegram_alert(lot: Lot, chat_id: str | int) -> bool:
    """Send a lot alert via Telegram (sync wrapper)."""
    return asyncio.run(_send_telegram_async(lot, chat_id))


async def send_telegram_text_async(text: str, chat_id: str | int) -> bool:
    """Send a plain text message to a Telegram chat."""
    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("Telegram bot token not configured")
        return False

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    try:
        await bot.send_message(
            chat_id=str(chat_id),
            text=text,
            parse_mode=ParseMode.HTML,
        )
        return True
    except TelegramError as exc:
        logger.error("Failed to send Telegram text to %s: %s", chat_id, exc)
        return False


def send_whatsapp_alert(lot: Lot) -> bool:
    """Send a lot alert via Twilio WhatsApp if enabled."""
    if not config.ENABLE_WHATSAPP:
        return False

    if not all(
        [
            config.TWILIO_ACCOUNT_SID,
            config.TWILIO_AUTH_TOKEN,
            config.TWILIO_WHATSAPP_FROM,
            config.WHATSAPP_TO_NUMBER,
        ]
    ):
        logger.error("WhatsApp/Twilio credentials not fully configured")
        return False

    try:
        from twilio.rest import Client
    except ImportError:
        logger.error("Twilio library not installed")
        return False

    message = format_lot_message_plain(lot)
    try:
        client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
        client.messages.create(
            body=message,
            from_=config.TWILIO_WHATSAPP_FROM,
            to=config.WHATSAPP_TO_NUMBER,
        )
        logger.info("WhatsApp alert sent for lot %s", lot.lot_number)
        return True
    except Exception as exc:
        logger.error("WhatsApp send failed for lot %s: %s", lot.lot_number, exc)
        return False


def notify_new_lot(lot: Lot, chat_id: str | int) -> bool:
    """
    Send alerts for a new lot to a specific user via Telegram.

    Returns True if Telegram delivery succeeded.
    """
    telegram_ok = send_telegram_alert(lot, chat_id)
    if config.ENABLE_WHATSAPP:
        send_whatsapp_alert(lot)
    return telegram_ok
