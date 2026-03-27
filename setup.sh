#!/bin/bash
set -e

echo "=== TradeX Bot Setup ==="
echo ""

source .venv/Scripts/activate

echo "Installing dependencies..."
pip install -r requirements.txt

echo ""
echo "Creating user data directory..."
freqtrade create-userdir --userdir user_data

echo ""
echo "Installing FreqUI dashboard..."
freqtrade install-ui

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit config.json — set your Hyperliquid wallet credentials:"
echo '     "walletAddress": "0xYOUR_WALLET_ADDRESS"'
echo '     "privateKey": "0xYOUR_PRIVATE_KEY"'
echo "  2. Start the bot:"
echo "     freqtrade trade --config config.json --strategy TradeXStrategy -v"
echo "  3. Open FreqUI dashboard:"
echo "     http://127.0.0.1:8080"
echo "     (Toggle dark theme via the theme button in FreqUI)"
echo "  4. For dry-run mode (no real orders):"
echo "     freqtrade trade --config config.json --strategy TradeXStrategy --dry-run -v"
