# TradeX Bot

Automated BTC/USDC perpetual futures trading bot built on [Freqtrade](https://www.freqtrade.io/), trading on [Hyperliquid](https://hyperliquid.xyz). Uses a breakout strategy with JMA and RSI confirmation, ATR-based risk management, trailing stops, and position pyramiding.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          TradeX Bot                                 │
│                                                                     │
│  ┌──────────────────┐    ┌──────────────────────────────────────┐  │
│  │   FreqUI (Web)   │    │         TradeXStrategy               │  │
│  │  localhost:8080  │◄──►│                                      │  │
│  │                  │    │  ┌────────────┐  ┌────────────────┐  │  │
│  │  • Dark theme    │    │  │ Indicators │  │  Entry Logic   │  │  │
│  │  • Live charts   │    │  │ ─────────  │  │ ─────────────  │  │  │
│  │  • P&L tracking  │    │  │ JMA(35)    │  │ high > H5      │  │  │
│  │  • Trade mgmt    │    │  │ RSI(35)    │  │ low  < L5      │  │  │
│  │  • Order book    │    │  │ ATR(14)    │  │ + JMA/RSI conf │  │  │
│  └──────────────────┘    │  │ Highest(5) │  └────────────────┘  │  │
│                           │  │ Lowest(5)  │                       │  │
│  ┌──────────────────┐    │  └────────────┘  ┌────────────────┐  │  │
│  │  Discord (opt.)  │    │                   │  Risk Mgmt     │  │  │
│  │                  │    │  ┌────────────┐   │ ─────────────  │  │  │
│  │  Trade alerts    │◄───│  │  Position  │   │ ATR stoploss   │  │  │
│  │  via webhook     │    │  │  Sizing    │   │ Trailing stop  │  │  │
│  └──────────────────┘    │  │ ─────────  │   │ 0.6% max loss  │  │  │
│                           │  │ $5  single │   └────────────────┘  │  │
│  ┌──────────────────┐    │  │ $10 double │                       │  │
│  │  SQLite DB       │    │  └────────────┘  ┌────────────────┐  │  │
│  │                  │    │                   │  Pyramiding    │  │  │
│  │  Trade history   │    │  ┌────────────┐   │ ─────────────  │  │  │
│  │  Order records   │◄───│  │  Leverage  │   │ Up to 4 adds   │  │  │
│  │  P&L data        │    │  │   50x      │   │ every 0.25%    │  │  │
│  └──────────────────┘    │  └────────────┘   └────────────────┘  │  │
│                           └──────────────────────────────────────┘  │
│                                        │                            │
│                                        ▼                            │
│                    ┌─────────────────────────────┐                 │
│                    │   Hyperliquid Exchange API   │                 │
│                    │   api.hyperliquid.xyz        │                 │
│                    │                             │                 │
│                    │   • BTC/USDC:USDC perp      │                 │
│                    │   • Isolated margin         │                 │
│                    │   • Limit orders only       │                 │
│                    │   • Real-time OHLCV (1m)    │                 │
│                    └─────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Strategy Overview

### Entry Conditions

```
LONG  ─► high > highest(previous 5 candle highs)
          + at least one of:
            • JMA(35) rising  (uptrend)
            • RSI(35) ≤ 35    (oversold)

SHORT ─► low < lowest(previous 5 candle lows)
          + at least one of:
            • JMA(35) falling  (downtrend)
            • RSI(35) ≥ 65     (overbought)
```

### Position Sizing

| Confirmations | Stake  | Leverage | Notional |
|---------------|--------|----------|----------|
| 1 of 2        | $5     | 50x      | $250     |
| 2 of 2        | $10    | 50x      | $500     |

### Risk Management

```
Stop Loss   = ATR(14) × 1.75   (capped at 0.6% of entry price)
Trailing    = activates at +0.4% profit, trails at 0.2%
Pyramiding  = up to 4 additional entries, every 0.25% in your favour
              (only after trailing stop has activated)
```

---

## Quick Start

### 1. Prerequisites
- Python 3.12+
- Git Bash or PowerShell on Windows
- Hyperliquid account with API wallet

### 2. Clone & Setup

```bash
git clone <repo-url>
cd V3Trader

# Activate virtual environment
source .venv/Scripts/activate        # Git Bash
# OR
.venv\Scripts\Activate.ps1           # PowerShell

# Install dependencies
pip install -r requirements.txt

# Install FreqUI dashboard
freqtrade install-ui
```

### 3. Configure

```bash
cp config.example.json config.json
```

Edit `config.json` and fill in:
```json
"walletAddress": "0xYOUR_HYPERLIQUID_WALLET",
"privateKey":    "YOUR_PRIVATE_KEY",
"password":      "strong-password-for-freqUI",
"jwt_secret_key": "random-32+-char-string"
```

> **Use an API sub-wallet**, not your main Hyperliquid wallet.
> API wallets can trade but cannot withdraw.

### 4. Run (Dry-Run — no real money)

```bash
freqtrade trade --config config.json --strategy TradeXStrategy -v --dry-run
```

### 5. Open Dashboard

Navigate to `http://127.0.0.1:8080` in your browser.
- Login with credentials from `config.json`
- Click the moon icon for dark theme

### 6. Share Dashboard (optional)

```bash
ngrok http 8080
# Paste the generated URL into Discord
```

---

## Going Live

When satisfied with dry-run performance:

1. Set `"dry_run": false` in `config.json`
2. Ensure your Hyperliquid wallet has USDC funded
3. Run without `--dry-run`:
```bash
freqtrade trade --config config.json --strategy TradeXStrategy -v
```

---

## Discord Notifications

Add to `config.json` to receive trade alerts in a Discord channel:

```json
"discord": {
    "enabled": true,
    "webhook_url": "https://discord.com/api/webhooks/YOUR_WEBHOOK"
}
```

Create a webhook: **Discord Server → Channel Settings → Integrations → Webhooks → New Webhook**

---

## File Structure

```
V3Trader/
├── config.json                 ← Your config (gitignored — has credentials)
├── config.example.json         ← Template — copy this to config.json
├── requirements.txt            ← Python dependencies
├── setup.bat / setup.sh        ← First-time setup scripts
├── CLAUDE.md                   ← AI assistant memory & project notes
├── README.md                   ← This file
└── user_data/
    ├── strategies/
    │   └── tradex_strategy.py  ← All trading logic
    ├── logs/
    │   └── tradex.log          ← Runtime logs (gitignored)
    ├── data/                   ← Downloaded OHLCV data (gitignored)
    └── notebooks/              ← Jupyter analysis notebooks
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| DNS timeout on Windows | `pip uninstall aiodns` (already done in setup) |
| `FastAPI.add_event_handler` error | `pip install fastapi==0.115.12 starlette==0.41.3` |
| `pairlists required` error | Ensure `config.json` has `"pairlists": [{"method": "StaticPairList"}]` |
| Hyperliquid testnet unreachable | Use mainnet + `dry_run: true` (testnet DNS unreliable) |
| VPN blocking connection | Disable VPN DNS proxy or disconnect VPN temporarily |

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `freqtrade` | Core trading framework |
| `pandas-ta` | JMA, RSI, ATR indicators |
| `ccxt` | Hyperliquid exchange connector |
| `fastapi` | FreqUI API server |
| `uvicorn` | ASGI server for FreqUI |
