"""
TradeX Bot Strategy
===================
Breakout strategy with JMA and RSI confirmation for BTC/USDC perpetual futures
on Hyperliquid. Implements ATR-based risk management, trailing stops, and pyramiding.

Entry Logic:
  Long:  high > highest(prev 5 highs) + JMA(35) uptrend OR RSI(35) <= 35
  Short: low  < lowest(prev 5 lows)  + JMA(35) downtrend OR RSI(35) >= 65

Position Sizing:
  Single confirmation: $5 USDC @ 50x leverage
  Double confirmation: $10 USDC @ 50x leverage

Risk Management:
  Stoploss: ATR(14) x 1.75, capped at 0.6% of entry
  Trailing: activates at +0.4% profit, trails at 0.2%
  Pyramiding: up to 4 adds at 0.25% intervals after trailing offset reached
"""

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
import pandas_ta as pta
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, stoploss_from_absolute
from freqtrade.strategy import merge_informative_pair
from pandas import DataFrame

logger = logging.getLogger(__name__)


class TradeXStrategy(IStrategy):
    """
    TradeX Bot — Breakout + JMA/RSI confirmation strategy for Hyperliquid futures.
    """

    INTERFACE_VERSION = 3

    # ─── Timeframe ────────────────────────────────────────────────────────
    # Primary: 1m for fast signal generation
    # Informative: 5m for multi-timeframe context
    # Change this single variable to switch timeframes (e.g., "5m", "1h")
    timeframe = "1m"
    informative_timeframe = "5m"

    # ─── Core settings ────────────────────────────────────────────────────
    can_short = True
    minimal_roi = {"0": 100}  # Disabled — exits via stoploss/trailing only
    stoploss = -0.02          # Absolute worst-case fallback (-2%)
    use_custom_stoploss = True

    # ─── Trailing stop (from spec) ────────────────────────────────────────
    trailing_stop = True
    trailing_stop_positive = 0.002           # 0.2% trail once in profit
    trailing_stop_positive_offset = 0.004    # Activate at 0.4% profit
    trailing_only_offset_is_reached = True

    # ─── Position adjustment / pyramiding ─────────────────────────────────
    position_adjustment_enable = True
    max_entry_position_adjustment = 4  # 4 adds = 5 total entries max

    # ─── Processing ───────────────────────────────────────────────────────
    process_only_new_candles = True
    startup_candle_count = 50  # Warmup for JMA(35), RSI(35), ATR(14)

    # ─── Order types (Hyperliquid requires limit orders) ──────────────────
    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "limit",
        "stoploss_on_exchange": True,
    }
    order_time_in_force = {
        "entry": "GTC",
        "exit": "GTC",
    }

    # ─── Strategy parameters ──────────────────────────────────────────────
    jma_length = 35
    rsi_length = 35
    atr_length = 14
    atr_multiplier = 1.75
    max_stoploss_pct = 0.006       # 0.6% max loss cap
    breakout_lookback = 5          # Candles for highest/lowest
    pyramid_interval_pct = 0.0025  # 0.25% between pyramid adds

    # ─── FreqUI plot configuration ────────────────────────────────────────
    plot_config = {
        "main_plot": {
            "jma_35": {"color": "#E0A800", "type": "line"},
        },
        "subplots": {
            "RSI": {
                "rsi_35": {"color": "#6CB4EE"},
            },
            "ATR": {
                "atr_14": {"color": "#FF6B6B"},
            },
        },
    }

    # ═════════════════════════════════════════════════════════════════════
    # INFORMATIVE PAIRS — Multi-timeframe data
    # ═════════════════════════════════════════════════════════════════════

    def informative_pairs(self):
        """Fetch 5m candles alongside the primary 1m timeframe."""
        pairs = self.dp.current_whitelist()
        informative = [(pair, self.informative_timeframe) for pair in pairs]
        return informative

    # ═════════════════════════════════════════════════════════════════════
    # INDICATORS
    # ═════════════════════════════════════════════════════════════════════

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Calculate all technical indicators on the 1m dataframe."""

        # ── JMA (Jurik Moving Average) ────────────────────────────────
        dataframe["jma_35"] = pta.jma(dataframe["close"], length=self.jma_length)

        # JMA trend direction
        dataframe["jma_uptrend"] = dataframe["jma_35"] > dataframe["jma_35"].shift(1)
        dataframe["jma_downtrend"] = dataframe["jma_35"] < dataframe["jma_35"].shift(1)

        # ── RSI ───────────────────────────────────────────────────────
        dataframe["rsi_35"] = pta.rsi(dataframe["close"], length=self.rsi_length)

        # ── ATR (for stoploss calculation) ────────────────────────────
        dataframe["atr_14"] = pta.atr(
            dataframe["high"], dataframe["low"], dataframe["close"],
            length=self.atr_length,
        )

        # ── Breakout levels (previous 5 candles, excluding current) ───
        dataframe["highest_high_5"] = (
            dataframe["high"].rolling(window=self.breakout_lookback).max().shift(1)
        )
        dataframe["lowest_low_5"] = (
            dataframe["low"].rolling(window=self.breakout_lookback).min().shift(1)
        )

        # ── Merge 5m informative data ─────────────────────────────────
        if self.dp:
            inf_df = self.dp.get_pair_dataframe(
                pair=metadata["pair"], timeframe=self.informative_timeframe
            )
            if not inf_df.empty:
                inf_df["jma_35_5m"] = pta.jma(inf_df["close"], length=self.jma_length)
                inf_df["rsi_35_5m"] = pta.rsi(inf_df["close"], length=self.rsi_length)
                dataframe = merge_informative_pair(
                    dataframe, inf_df, self.timeframe, self.informative_timeframe,
                    ffill=True,
                )

        return dataframe

    # ═════════════════════════════════════════════════════════════════════
    # ENTRY SIGNALS
    # ═════════════════════════════════════════════════════════════════════

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Generate entry signals with confirmation-based tags for position sizing.

        Tags:
          long_double_confirm  / short_double_confirm  → $10 stake
          long_single_confirm  / short_single_confirm  → $5 stake
        """

        # ── Long conditions ───────────────────────────────────────────
        breakout_long = dataframe["high"] > dataframe["highest_high_5"]
        jma_confirm_long = dataframe["jma_uptrend"]
        rsi_confirm_long = dataframe["rsi_35"] <= 35

        both_long = breakout_long & jma_confirm_long & rsi_confirm_long
        single_long = (
            breakout_long
            & (jma_confirm_long | rsi_confirm_long)
            & ~both_long
        )

        # ── Short conditions ──────────────────────────────────────────
        breakout_short = dataframe["low"] < dataframe["lowest_low_5"]
        jma_confirm_short = dataframe["jma_downtrend"]
        rsi_confirm_short = dataframe["rsi_35"] >= 65

        both_short = breakout_short & jma_confirm_short & rsi_confirm_short
        single_short = (
            breakout_short
            & (jma_confirm_short | rsi_confirm_short)
            & ~both_short
        )

        # ── Set signals (double-confirm first for priority) ───────────
        dataframe.loc[both_long, ["enter_long", "enter_tag"]] = (
            1, "long_double_confirm"
        )
        dataframe.loc[single_long, ["enter_long", "enter_tag"]] = (
            1, "long_single_confirm"
        )

        dataframe.loc[both_short, ["enter_short", "enter_tag"]] = (
            1, "short_double_confirm"
        )
        dataframe.loc[single_short, ["enter_short", "enter_tag"]] = (
            1, "short_single_confirm"
        )

        # Log signal counts for retrospective analysis
        long_count = both_long.sum() + single_long.sum()
        short_count = both_short.sum() + single_short.sum()
        if long_count > 0 or short_count > 0:
            logger.info(
                f"{metadata['pair']} signals — "
                f"Long: {long_count} (double: {both_long.sum()}, single: {single_long.sum()}) | "
                f"Short: {short_count} (double: {both_short.sum()}, single: {single_short.sum()})"
            )

        return dataframe

    # ═════════════════════════════════════════════════════════════════════
    # EXIT SIGNALS
    # ═════════════════════════════════════════════════════════════════════

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Exits handled by trailing stop and custom stoploss.
        No signal-based exits by default.

        Uncomment below to enable counter-signal exits:
        exit long when short breakout fires, and vice versa.
        """
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0

        # # ── Optional: counter-signal exits ─────────────────────────
        # breakout_short = dataframe["low"] < dataframe["lowest_low_5"]
        # jma_down = dataframe["jma_downtrend"]
        # rsi_over = dataframe["rsi_35"] >= 65
        # dataframe.loc[
        #     breakout_short & (jma_down | rsi_over), "exit_long"
        # ] = 1
        #
        # breakout_long = dataframe["high"] > dataframe["highest_high_5"]
        # jma_up = dataframe["jma_uptrend"]
        # rsi_under = dataframe["rsi_35"] <= 35
        # dataframe.loc[
        #     breakout_long & (jma_up | rsi_under), "exit_short"
        # ] = 1

        return dataframe

    # ═════════════════════════════════════════════════════════════════════
    # POSITION SIZING — $5 (single) or $10 (double confirmation)
    # ═════════════════════════════════════════════════════════════════════

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        """Return $10 for double confirmation, $5 for single."""
        if entry_tag and "double_confirm" in entry_tag:
            stake = 10.0
        else:
            stake = 5.0

        # Clamp to exchange limits
        if min_stake is not None:
            stake = max(stake, min_stake)
        stake = min(stake, max_stake)

        logger.info(
            f"{pair} stake=${stake:.2f} (tag={entry_tag}, side={side}, "
            f"leverage={leverage}x, notional=${stake * leverage:.0f})"
        )
        return stake

    # ═════════════════════════════════════════════════════════════════════
    # LEVERAGE — 50x for all entries
    # ═════════════════════════════════════════════════════════════════════

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        """Always use 50x leverage (capped by exchange max)."""
        return min(50.0, max_leverage)

    # ═════════════════════════════════════════════════════════════════════
    # CUSTOM STOPLOSS — ATR-based with 0.6% cap
    # ═════════════════════════════════════════════════════════════════════

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> Optional[float]:
        """
        Dynamic stoploss based on ATR(14) x 1.75, capped at 0.6%.

        Long:  stoploss = entry - min(ATR * 1.75, 0.6% of price)
        Short: stoploss = entry + min(ATR * 1.75, 0.6% of price)

        Interacts with trailing stop — Freqtrade uses whichever is tighter.
        """
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if len(dataframe) < 1:
            return None

        last_candle = dataframe.iloc[-1]
        atr = last_candle.get("atr_14")

        if pd.isna(atr) or atr <= 0:
            return None

        # ATR-based distance
        atr_distance = atr * self.atr_multiplier

        # Cap at 0.6% of current price
        max_distance = current_rate * self.max_stoploss_pct

        stoploss_distance = min(atr_distance, max_distance)

        # Absolute stoploss price
        if trade.is_short:
            stoploss_price = current_rate + stoploss_distance
        else:
            stoploss_price = current_rate - stoploss_distance

        result = stoploss_from_absolute(
            stoploss_price,
            current_rate=current_rate,
            is_short=trade.is_short,
            leverage=trade.leverage,
        )

        logger.debug(
            f"{pair} stoploss — ATR={atr:.2f}, distance={stoploss_distance:.2f} "
            f"({'capped' if atr_distance > max_distance else 'ATR'}), "
            f"price={stoploss_price:.2f}, ratio={result:.4f}"
        )

        return result

    # ═════════════════════════════════════════════════════════════════════
    # PYRAMIDING — Add to winning positions
    # ═════════════════════════════════════════════════════════════════════

    def adjust_trade_position(
        self,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: Optional[float],
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs,
    ) -> Optional[float]:
        """
        Pyramid into winning positions:
        - Only after trailing_stop_positive_offset (0.4%) is reached
        - Add every 0.25% price increase from last pyramid entry
        - Up to 4 additional entries (5 total)
        - $5 per pyramid add
        """
        # Only pyramid after trailing offset is reached
        if current_profit < self.trailing_stop_positive_offset:
            return None

        # Check how many entries we already have
        filled_entries = trade.select_filled_orders(trade.entry_side)
        num_entries = len(filled_entries)

        if num_entries >= 5:  # 1 initial + 4 pyramids max
            return None

        # Get the price of the last filled entry
        last_entry_order = filled_entries[-1]
        last_entry_price = last_entry_order.safe_price

        # Calculate price movement since last entry
        if trade.is_short:
            price_change_pct = (last_entry_price - current_rate) / last_entry_price
        else:
            price_change_pct = (current_rate - last_entry_price) / last_entry_price

        # Only add if price moved 0.25% beyond last entry in favorable direction
        if price_change_pct < self.pyramid_interval_pct:
            return None

        # $5 per pyramid add
        pyramid_stake = 5.0
        if min_stake is not None:
            pyramid_stake = max(pyramid_stake, min_stake)
        pyramid_stake = min(pyramid_stake, max_stake)

        logger.info(
            f"{trade.pair} PYRAMID #{num_entries} — "
            f"profit={current_profit:.4f}, price_change={price_change_pct:.4f}, "
            f"stake=${pyramid_stake:.2f}, last_entry={last_entry_price:.2f}"
        )

        return pyramid_stake
