# TradeX Bot — Claude Code Memory

## Project Identity
- **Name**: TradeX Bot
- **Framework**: Freqtrade 2026.2
- **Language**: Python 3.12.10 (.venv)
- **Exchange**: Hyperliquid (mainnet API, dry-run mode for testing)
- **Market**: BTC/USDC:USDC perpetual futures
- **Strategy file**: `user_data/strategies/tradex_strategy.py`
- **Config**: `config.json` (gitignored — contains private key)

## Environment
- **OS**: Windows 11, shell: bash (Git Bash / PowerShell)
- **Venv**: `.venv/Scripts/activate` or `.venv\Scripts\Activate.ps1`
- **aiodns REMOVED** — caused Windows DNS failures; aiohttp uses threaded resolver instead
- **FastAPI pinned** to `0.115.12` + Starlette `0.41.3` — Freqtrade incompatible with Starlette 1.0.0

## Known Issues & Fixes Applied
| Issue | Fix |
|-------|-----|
| `aiodns` DNS timeout on Windows with VPN | `pip uninstall aiodns` |
| `FastAPI.add_event_handler` removed in Starlette 1.0.0 | `pip install fastapi==0.115.12 starlette==0.41.3` |
| `pairlists` required by Freqtrade config schema | Added `StaticPairList` to config.json |
| Hyperliquid testnet unreachable | Use mainnet + `dry_run: true` |

## Strategy Logic Summary

### Entry
| Side  | Breakout Condition         | Confirmation Required (at least 1) | Stake |
|-------|---------------------------|--------------------------------------|-------|
| Long  | high > highest(prev 5)    | JMA(35) uptrend OR RSI(35) ≤ 35     | $5    |
| Short | low < lowest(prev 5)      | JMA(35) downtrend OR RSI(35) ≥ 65   | $5    |
| Both  | (same as above)           | BOTH confirmations fire              | $10   |

### Risk
- Stoploss: ATR(14) × 1.75, capped at 0.6% of entry
- Trailing: activates at +0.4%, trails at 0.2%
- Leverage: 50x (via `leverage()` callback)
- Pyramiding: up to 4 adds at 0.25% intervals (only after trailing offset reached)

## Key Files
```
config.json                              ← gitignored, has credentials
config.example.json                      ← template for new setups
user_data/strategies/tradex_strategy.py  ← all strategy logic
```

## Run Commands
```bash
# Dry-run (safe testing)
freqtrade trade --config config.json --strategy TradeXStrategy -v --dry-run

# Live trading (set dry_run: false in config.json first)
freqtrade trade --config config.json --strategy TradeXStrategy -v

# FreqUI dashboard
http://127.0.0.1:8080   (username: tradex)

# Share UI publicly (requires ngrok)
ngrok http 8080
```

## Do Not
- Do NOT commit `config.json` (contains private key)
- Do NOT re-install `aiodns` (breaks DNS on Windows/VPN)
- Do NOT upgrade `fastapi` above `0.115.12` or `starlette` above `0.41.3`
- Do NOT set `dry_run: false` without verifying strategy on paper first
