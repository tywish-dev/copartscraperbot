# Copart Scraper Bot

A Python bot that monitors [Copart.com](https://www.copart.com) for vehicles matching your preferences and sends alerts via **Telegram** (primary) and optionally **WhatsApp** (Twilio).

## Features

- Scrapes Copart **lotSearchResults** pages in a real Chrome browser (undetected-chromedriver)
- Builds search URLs with the same `searchCriteria` filter format Copart uses on the website
- Extracts lots via in-browser XHR (using page cookies) and DOM table parsing
- Filters lots by make, year, odometer, buy-now price, damage type, and location
- SQLite database prevents duplicate notifications
- Scheduled scans every 30 minutes (configurable)
- Telegram commands: `/start`, `/preferences`, `/check`, `/status`
- Exponential backoff on Copart blocks (403/captcha)
- Logs to `bot.log` with timestamps

## Project Structure

```
copartscraperbot/
├── main.py           # Entry point, scheduler, Telegram commands
├── scraper.py        # Copart search & scraping logic
├── filters.py        # Car preference filtering logic
├── notifier.py       # Telegram + WhatsApp messaging
├── db.py             # SQLite to track already-seen lots
├── config.py         # User settings & credentials
├── requirements.txt
├── .env.example      # Environment template (copy to .env)
└── README.md
```

## Setup

### 1. Clone and install dependencies

```bash
git clone <your-repo-url>
cd copartscraperbot
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

```bash
copy .env.example .env   # Windows
# cp .env.example .env   # macOS/Linux
```

Edit `.env` and fill in your credentials (see sections below).

### 3. Adjust car preferences

Edit `config.py` to set your preferred makes, price limits, damage exclusions, and locations:

```python
PREFERRED_MAKES = ["BMW", "Mercedes", "Audi", "Toyota"]
MAX_ODOMETER = 120_000
MAX_BUY_NOW_PRICE = 8_000
MIN_YEAR = 2015
EXCLUDED_DAMAGE = ["FIRE", "FLOOD", "VANDALISM"]
ONLY_BUY_NOW = True
PREFERRED_LOCATIONS = ["TX", "CA", "FL"]
```

### 4. Run the bot

```bash
python main.py
```

The bot will:
1. Run an initial scan immediately
2. Start polling Telegram for commands
3. Schedule automatic scans every `CHECK_INTERVAL_MINUTES` (default: 30)

## Telegram Setup

### Get a Bot Token (via @BotFather)

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts to name your bot
3. BotFather replies with a token like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`
4. Paste it into `.env` as `TELEGRAM_BOT_TOKEN`

### Get Your Chat ID

**Option A — via @userinfobot**
1. Search for [@userinfobot](https://t.me/userinfobot) on Telegram
2. Start a chat — it replies with your numeric user ID
3. Paste it into `.env` as `TELEGRAM_CHAT_ID`

**Option B — via API**
1. Send any message to your new bot first
2. Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Find `"chat":{"id":123456789}` in the JSON response
4. Use that number as `TELEGRAM_CHAT_ID`

### Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and command list |
| `/preferences` | Show current filter settings |
| `/check` | Trigger an immediate Copart scan |
| `/status` | Last scrape time and bot stats |

## WhatsApp Setup (Optional — Twilio Sandbox)

WhatsApp alerts are disabled by default. To enable:

1. Create a [Twilio account](https://www.twilio.com/try-twilio)
2. In the Twilio Console, go to **Messaging → Try it out → Send a WhatsApp message**
3. Follow the sandbox instructions — send the join code from your phone to `+1 415 523 8886`
4. Fill in `.env`:

```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
WHATSAPP_TO_NUMBER=whatsapp:+1XXXXXXXXXX
ENABLE_WHATSAPP=true
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | Your Telegram chat/user ID |
| `TWILIO_ACCOUNT_SID` | No | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | No | Twilio auth token |
| `TWILIO_WHATSAPP_FROM` | No | Twilio WhatsApp sender number |
| `WHATSAPP_TO_NUMBER` | No | Your WhatsApp number (Twilio format) |
| `ENABLE_WHATSAPP` | No | `true` to enable WhatsApp alerts |
| `CHECK_INTERVAL_MINUTES` | No | Scan interval (default: 30) |

## Error Handling

- **Copart blocks (403/captcha):** Retries up to 3 times with exponential backoff, then falls back to the next scrape strategy
- **Telegram send failure:** Retries once after 60 seconds
- **Scheduler errors:** Logged to `bot.log`; the scheduler continues running

## Logs & Database

- **Logs:** `bot.log` (auto-created)
- **Seen lots DB:** `seen_lots.db` (auto-created, gitignored)

## Browser Scraper

Copart blocks direct API calls (403). The bot uses **undetected-chromedriver** to load real search pages like:

`https://www.copart.com/lotSearchResults?...&searchCriteria={...}`

For each preferred make (and optional model), it:

1. Opens the search URL in headless Chrome
2. Waits for the results table to render
3. Fetches lot data via in-browser XHR (uses the page session/cookies)
4. Falls back to parsing the rendered HTML table rows

**Requirements:** Google Chrome (preferred) or Microsoft Edge. Chrome is used via `undetected-chromedriver`; if Chrome is not installed, the bot falls back to Edge automatically.

To restrict models (e.g. Tesla Model S only), edit `config.py`:

```python
PREFERRED_MODELS = {
    "Tesla": ["Model S"],
}
```

Set `SELENIUM_HEADLESS=false` in `.env` to watch the browser while debugging.

## License

MIT

## Connect to GitHub

After cloning locally, push this repo to GitHub:

```bash
# 1. Authenticate (one-time)
gh auth login

# 2. Create the remote repo and push
gh repo create copartscraperbot --private --source=. --remote=origin --push
```

Or, if you already created an empty repo on GitHub:

```bash
git remote add origin https://github.com/YOUR_USERNAME/copartscraperbot.git
git push -u origin main
```
