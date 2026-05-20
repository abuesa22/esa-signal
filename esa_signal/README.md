# ESA Signal

Personal AI-powered signal and intelligence bot.  
Scans crypto markets 24/7, delivers verified alerts and daily market briefs via Telegram.  
**Never touches your wallet. You execute manually.**

---

## What It Does

| Feature | Detail |
|---|---|
| Crypto Scanner | Scans DexScreener every 15 min for new Solana/ETH tokens |
| 4-Gate Filter | Safety → Legitimacy → Momentum → Market Cap |
| AI Scoring | Claude scores every passing token 0–100 |
| Morning Brief | 7:00 AM AEST — futures, macro, events, narratives |
| Midday Update | 12:00 PM AEST — moves, movers, breaking news |
| Evening Brief | 9:00 PM AEST — US close, sectors, Claude outlook |
| SQLite Database | Stores every signal + win/loss tracking |
| Telegram Commands | /stats /history /top /market /outcome |

---

## Setup

### 1. Prerequisites

- Python 3.11+
- A Telegram bot (create via [@BotFather](https://t.me/BotFather))
- Your Telegram Chat ID (message [@userinfobot](https://t.me/userinfobot))

### 2. Create your .env file

Your `.env.txt` file is already in the parent folder.  
Rename it to `.env` OR create a new `.env` inside the `esa_signal/` directory:

```
cd "C:\Users\Esa\OneDrive\Desktop\esa signal\esa_signal"
```

Create `.env` with this content (no spaces around `=`):

```
TELEGRAM_BOT_TOKEN=8791430599:AAFh1cj2fY69XDF6w_mjMezfx05-kmMk348
TELEGRAM_CHAT_ID=8351895169
COINGECKO_API_KEY=CG-4pHeEwQ4cUWwPccVzAsJWH5g
CMC_API_KEY=92f0734e8a644b8f899010cd44618515
FINNHUB_API_KEY=d80o019r01qt5k5vlasgd80o019r01qt5k5vlat0
ALPHA_VANTAGE_API_KEY=ONM1WGLP4YWG84IA
ANTHROPIC_API_KEY=sk-ant-api03-...your-key...
```

### 3. Install dependencies

```bash
cd "C:\Users\Esa\OneDrive\Desktop\esa signal\esa_signal"
pip install -r requirements.txt
```

### 4. Run the bot

```bash
python main.py
```

You'll see a startup message in Telegram immediately.  
Press `Ctrl+C` to stop.

---

## Running 24/7 on Windows

Use Task Scheduler or NSSM to run the bot as a Windows service:

**Option A — Windows Task Scheduler**
1. Open Task Scheduler → Create Basic Task
2. Trigger: At startup
3. Action: `python "C:\Users\Esa\OneDrive\Desktop\esa signal\esa_signal\main.py"`
4. Set working directory to `C:\Users\Esa\OneDrive\Desktop\esa signal\esa_signal`

**Option B — PM2 (Node-based process manager)**
```bash
npm install -g pm2
pm2 start python --name "esa-signal" -- main.py
pm2 save
pm2 startup
```

---

## Telegram Commands

| Command | Description |
|---|---|
| `/start` | Show help and command list |
| `/stats` | Win rate, total signals, outcome breakdown |
| `/history` | Last 10 signals sent |
| `/top` | Best performing signals ever |
| `/market` | Trigger a manual market brief right now |
| `/outcome [id] [result]` | Update a signal outcome |

**Outcome values:** `2x` `5x` `10x` `LOSS` `HOLD`

Example: `/outcome 42 5x`

---

## Signal Flow

```
DexScreener new token
       │
  GATE 1: Safety
  (Rugcheck + age + liquidity + no mint auth)
       │ PASS
  GATE 2: Legitimacy
  (CoinGecko/CMC listing + volume > $100K)
       │ PASS
  GATE 3: Momentum
  (Price +20% 1h + volume accelerating + buy pressure)
       │ PASS
  GATE 4: Market Cap
  (MC < $10M + FDV sane)
       │ PASS
  Claude AI Scoring (0–100)
       │ Score ≥ 70
  Telegram Alert Sent
       │
  SQLite stored (you add outcome manually)
```

---

## File Structure

```
esa_signal/
├── main.py              ← Run this
├── config.py            ← All settings and thresholds
├── scheduler.py         ← APScheduler job setup
├── scanner/
│   ├── crypto_scanner.py    ← Main scan orchestrator
│   ├── safety_checker.py    ← Gate 1
│   ├── legitimacy_checker.py ← Gate 2
│   └── momentum_checker.py  ← Gates 3 & 4
├── markets/
│   ├── stock_scanner.py     ← Data fetchers
│   └── market_brief.py      ← Brief composers
├── ai/
│   ├── scorer.py            ← Token scoring
│   └── analyser.py          ← Market outlook + narratives
├── bot/
│   ├── telegram_bot.py      ← Bot + commands
│   └── formatters.py        ← Message formatting
├── database/
│   ├── db.py                ← SQLite operations
│   └── models.py            ← Data models
├── utils/
│   ├── helpers.py           ← HTTP retry, formatting
│   └── rate_limiter.py      ← API rate limiting
├── requirements.txt
├── .env.example
└── README.md
```

---

## Adjusting Thresholds

All scanner thresholds are in `config.py`. Key ones:

| Setting | Default | Meaning |
|---|---|---|
| `MIN_LIQUIDITY_USD` | $50,000 | Gate 1 liquidity floor |
| `MAX_MARKET_CAP_USD` | $10,000,000 | Gate 4 MC ceiling |
| `MIN_VOLUME_24H_USD` | $100,000 | Gate 2 volume floor |
| `MIN_PRICE_CHANGE_1H_PCT` | 20% | Gate 3 momentum floor |
| `MIN_AI_SCORE` | 70 | Minimum Claude score to alert |
| `SCAN_INTERVAL_MINUTES` | 15 | How often to scan |

---

## API Rate Limits (Free Tiers)

| API | Free Limit | Used For |
|---|---|---|
| CoinGecko Demo | 30 req/min | Legitimacy check, trending |
| CMC Free | 30 req/min | Legitimacy check |
| Alpha Vantage | 5 req/min | Top movers |
| Finnhub | 60 req/min | Events, earnings, news |
| DexScreener | 300 req/min | Token discovery |
| Rugcheck | 100 req/min | Safety check (Solana) |
| Anthropic | 50 req/min | AI scoring |

The built-in rate limiter (`utils/rate_limiter.py`) enforces all limits automatically.

---

## Logs

- Console: INFO level (all activity)  
- `errors.log`: WARNING and above only (auto-rotates at 5MB)

---

## Disclaimer

ESA Signal provides information only. Nothing here is financial advice.  
The bot never has wallet access. All trades are executed manually by you.  
Past signal performance does not guarantee future results.
