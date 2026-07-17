import unittest
from unittest.mock import patch

import pandas as pd

import config
from strategy import (
    _intraday_entry_context,
    _intraday_setup_context,
    _intraday_trigger_context,
    _signal_threshold,
    _trend_health_context,
    futures_context_priority,
    should_fetch_futures_context,
)


def trend_frame(side="BUY", rows=60):
    data = []

    for index in range(rows):
        direction = index * 0.12
        close = 100 + direction if side == "BUY" else 110 - direction
        ema20 = close - 0.4 if side == "BUY" else close + 0.4
        ema50 = close - 1.0 if side == "BUY" else close + 1.0
        ema200 = close - 2.0 if side == "BUY" else close + 2.0
        data.append({
            "open": close - 0.1 if side == "BUY" else close + 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "atr": 1.0,
            "adx": 25.0,
            "adx_slope": 0.5,
            "efficiency_ratio": 0.45,
            "di_spread": 12.0 if side == "BUY" else -12.0,
            "session_vwap": close - 0.2 if side == "BUY" else close + 0.2,
            "macd_hist": 0.2 if side == "BUY" else -0.2,
        })

    data.append(dict(data[-1]))
    return pd.DataFrame(data)


def setup_frame(side="BUY", rows=16):
    data = []

    for index in range(rows):
        base = 100 + (index * 0.05) if side == "BUY" else 102 - (index * 0.05)
        data.append({
            "open": base,
            "high": base + 0.6,
            "low": base - 0.6,
            "close": base + 0.2 if side == "BUY" else base - 0.2,
            "atr": 1.0,
            "ema20": base,
            "ema50": base - 0.8 if side == "BUY" else base + 0.8,
            "session_vwap": base - 0.1 if side == "BUY" else base + 0.1,
            "macd_hist": 0.15 if side == "BUY" else -0.15,
            "rsi": 54.0 if side == "BUY" else 46.0,
            "volume": 100.0,
            "volume_sma": 100.0,
            "volume_ratio": 1.0,
        })

    data.append(dict(data[-1]))
    return pd.DataFrame(data)


def trigger_frame(side="BUY", chase=False):
    data = []

    for index in range(10):
        base = 100 + (index * 0.02) if side == "BUY" else 102 - (index * 0.02)
        data.append({
            "open": base,
            "high": base + 0.35,
            "low": base - 0.35,
            "close": base,
            "atr": 1.0,
            "ema20": base,
            "session_vwap": base,
            "macd_hist": 0.02 if side == "BUY" else -0.02,
            "volume": 100.0,
            "volume_sma": 100.0,
            "volume_ratio": 1.0,
        })

    previous = data[-1]

    if side == "BUY":
        close = 102.5 if chase else 101.0
        latest = {
            "open": 100.15,
            "high": close + 0.15,
            "low": 100.05,
            "close": close,
            "atr": 1.0,
            "ema20": 100.25,
            "session_vwap": 100.20,
            "macd_hist": 0.12,
            "volume": 110.0,
            "volume_sma": 100.0,
            "volume_ratio": 1.1,
        }
    else:
        close = 99.5 if chase else 101.0
        latest = {
            "open": 101.85,
            "high": 101.95,
            "low": close - 0.15,
            "close": close,
            "atr": 1.0,
            "ema20": 101.65,
            "session_vwap": 101.70,
            "macd_hist": -0.12,
            "volume": 110.0,
            "volume_sma": 100.0,
            "volume_ratio": 1.1,
        }

    previous["macd_hist"] = 0.02 if side == "BUY" else -0.02
    data.append(latest)
    data.append(dict(latest))
    return pd.DataFrame(data)


class IntradayEntryTests(unittest.TestCase):
    def setUp(self):
        settings = {
            "TREND_HEALTH_ENABLED": True,
            "TREND_HEALTH_MIN_EFFICIENCY_RATIO": 0.18,
            "TREND_HEALTH_MIN_ADX_SLOPE": -1,
            "TREND_HEALTH_MAX_WARNING_POINTS": 4.5,
            "TREND_HEALTH_HARD_BLOCK_POINTS": 6.5,
            "INTRADAY_ENTRY_ENABLED": True,
            "INTRADAY_MIN_CONFIDENCE": 74,
            "INTRADAY_MIN_TREND_SCORE": 7,
            "INTRADAY_MIN_CONFIRM_SCORE": 6,
            "INTRADAY_SETUP_LOOKBACK": 6,
            "INTRADAY_SETUP_STRUCTURE_LOOKBACK": 8,
            "INTRADAY_SETUP_MIN_POINTS": 5,
            "INTRADAY_TRIGGER_STRUCTURE_LOOKBACK": 8,
            "INTRADAY_TRIGGER_MIN_BODY_ATR": 0.2,
            "INTRADAY_TRIGGER_MIN_CLOSE_POSITION": 0.58,
            "INTRADAY_TRIGGER_MIN_POINTS": 4,
            "INTRADAY_TRIGGER_MIN_VOLUME_MULT": 1,
            "INTRADAY_TRIGGER_REQUIRE_MOMENTUM_OR_FLOW": True,
            "INTRADAY_TRIGGER_FLOW_SUPPORT_SCORE": 0.5,
            "INTRADAY_MAX_CHASE_ATR": 1,
            "INTRADAY_REQUIRE_FUTURES": True,
            "INTRADAY_MIN_FUTURES_SCORE": 0,
            "INTRADAY_ESTABLISHED_MIN_CONFIDENCE": 72,
            "INTRADAY_ESTABLISHED_MIN_TREND_SCORE": 7,
            "INTRADAY_ESTABLISHED_MIN_CONFIRM_SCORE": 6,
            "INTRADAY_TRANSITION_ENABLED": True,
            "INTRADAY_TRANSITION_MIN_CONFIDENCE": 76,
            "INTRADAY_TRANSITION_MIN_TREND_SCORE": 7.5,
            "INTRADAY_TRANSITION_MIN_CONFIRM_SCORE": 6.5,
            "INTRADAY_TRANSITION_MIN_FUTURES_SCORE": 0.5,
            "INTRADAY_TRANSITION_REQUIRE_BREAKOUT_RETEST": True,
        }
        self.config_patches = [
            patch.object(config, name, value)
            for name, value in settings.items()
        ]

        for config_patch in self.config_patches:
            config_patch.start()

    def tearDown(self):
        for config_patch in reversed(self.config_patches):
            config_patch.stop()

    def test_valid_setup_and_trigger_activate_with_futures_context(self):
        trend = trend_frame()
        confirm = setup_frame()
        entry = trigger_frame()
        health = _trend_health_context(
            "BUY",
            trend,
            confirm,
            participation_score=0,
            participation={"available": True},
        )
        result = _intraday_entry_context(
            "BUY",
            confirm,
            entry,
            trend_ok=True,
            level_ok=True,
            trend_score=9,
            confirm_score=8,
            trend_confidence=82,
            entry_quality={"late_entry_ok": True},
            trend_health=health,
            participation_score=0,
            participation={"available": True},
            futures_ok=True,
        )

        self.assertTrue(health["healthy"])
        self.assertTrue(result["setup"]["valid"])
        self.assertTrue(result["trigger"]["valid"])
        self.assertTrue(result["eligible"])
        self.assertTrue(result["active"])
        self.assertEqual(result["route"], "ESTABLISHED")

    def test_established_route_uses_its_route_specific_threshold(self):
        health = _trend_health_context("BUY", trend_frame(), setup_frame())
        result = _intraday_entry_context(
            "BUY",
            setup_frame(),
            trigger_frame(),
            trend_ok=True,
            level_ok=True,
            trend_score=8,
            confirm_score=7,
            trend_confidence=73,
            entry_quality={"late_entry_ok": True},
            trend_health=health,
            participation_score=0,
            participation={"available": True},
            futures_ok=True,
        )

        self.assertTrue(result["active"])
        self.assertEqual(result["required_confidence"], 72)
        self.assertEqual(
            _signal_threshold({
                "confirmation_type": "TREND",
                "intraday_entry": result,
            }),
            72,
        )

    def test_eligible_entry_waits_for_futures_context(self):
        health = _trend_health_context("BUY", trend_frame(), setup_frame())
        result = _intraday_entry_context(
            "BUY",
            setup_frame(),
            trigger_frame(),
            trend_ok=True,
            level_ok=True,
            trend_score=9,
            confirm_score=8,
            trend_confidence=82,
            entry_quality={"late_entry_ok": True},
            trend_health=health,
            participation_score=0,
            participation=None,
            futures_ok=True,
        )

        self.assertTrue(result["eligible"])
        self.assertFalse(result["active"])
        self.assertEqual(result["reason"], "INTRADAY_ENTRY_AWAITING_FUTURES")

    def test_chasing_trigger_is_rejected(self):
        result = _intraday_trigger_context("BUY", trigger_frame(chase=True))

        self.assertFalse(result["valid"])
        self.assertFalse(result["not_chasing"])

    def test_trigger_needs_chart_momentum_or_supportive_futures_flow(self):
        entry = trigger_frame()
        current_index = len(entry) - 2
        previous_index = len(entry) - 3
        entry.loc[previous_index, "macd_hist"] = 0.02
        entry.loc[current_index, "macd_hist"] = 0.01
        entry.loc[current_index, "volume"] = 80
        entry.loc[current_index, "volume_ratio"] = 0.8
        health = _trend_health_context("BUY", trend_frame(), setup_frame())

        blocked = _intraday_entry_context(
            "BUY",
            setup_frame(),
            entry,
            trend_ok=True,
            level_ok=True,
            trend_score=9,
            confirm_score=8,
            trend_confidence=82,
            entry_quality={"late_entry_ok": True},
            trend_health=health,
            participation_score=0,
            participation={"available": True},
            futures_ok=True,
        )
        supported = _intraday_entry_context(
            "BUY",
            setup_frame(),
            entry,
            trend_ok=True,
            level_ok=True,
            trend_score=9,
            confirm_score=8,
            trend_confidence=82,
            entry_quality={"late_entry_ok": True},
            trend_health=health,
            participation_score=0.75,
            participation={"available": True},
            futures_ok=True,
        )

        self.assertFalse(blocked["eligible"])
        self.assertIn(
            "INTRADAY_TRIGGER_MOMENTUM_OR_FLOW_REQUIRED",
            blocked["reasons"],
        )
        self.assertTrue(supported["active"])
        self.assertTrue(supported["flow_support"])

    def test_transition_route_requires_breakout_retest_and_structure(self):
        setup = {
            "valid": True,
            "reason": "INTRADAY_SETUP_VALID",
            "breakout_retest": True,
            "type": "BREAKOUT_RETEST",
            "points": 6,
        }
        trigger = {
            "valid": True,
            "reason": "INTRADAY_TRIGGER_VALID",
            "structural_event": True,
            "chart_momentum_support": True,
            "points": 6,
        }
        health = {"healthy": True, "market_state": "TRANSITION"}

        with patch(
            "strategy._intraday_setup_context",
            return_value=setup,
        ), patch(
            "strategy._intraday_trigger_context",
            return_value=trigger,
        ):
            accepted = _intraday_entry_context(
                "BUY",
                setup_frame(),
                trigger_frame(),
                trend_ok=True,
                level_ok=True,
                trend_score=8,
                confirm_score=7,
                trend_confidence=78,
                entry_quality={"late_entry_ok": True},
                trend_health=health,
                participation_score=0.75,
                participation={"available": True},
                futures_ok=True,
            )

        with patch(
            "strategy._intraday_setup_context",
            return_value={**setup, "breakout_retest": False},
        ), patch(
            "strategy._intraday_trigger_context",
            return_value=trigger,
        ):
            blocked = _intraday_entry_context(
                "BUY",
                setup_frame(),
                trigger_frame(),
                trend_ok=True,
                level_ok=True,
                trend_score=8,
                confirm_score=7,
                trend_confidence=78,
                entry_quality={"late_entry_ok": True},
                trend_health=health,
                participation_score=0.75,
                participation={"available": True},
                futures_ok=True,
            )

        self.assertTrue(accepted["active"])
        self.assertEqual(accepted["route"], "TRANSITION")
        self.assertFalse(blocked["eligible"])
        self.assertIn(
            "TRANSITION_BREAKOUT_RETEST_REQUIRED",
            blocked["reasons"],
        )

    def test_trend_health_separates_established_and_transition_states(self):
        established = _trend_health_context(
            "BUY",
            trend_frame(),
            setup_frame(),
        )
        partial_stack = trend_frame()
        closed_index = len(partial_stack) - 2
        partial_stack.loc[closed_index, "ema200"] = (
            partial_stack.loc[closed_index, "ema50"] + 0.5
        )
        transition = _trend_health_context(
            "BUY",
            partial_stack,
            setup_frame(),
        )

        self.assertEqual(established["market_state"], "ESTABLISHED")
        self.assertEqual(transition["market_state"], "TRANSITION")

    def test_confirmed_structure_and_ema_failure_blocks_trend_health(self):
        trend = trend_frame()
        confirm = setup_frame()
        closed_index = len(confirm) - 2
        confirm.loc[closed_index, "close"] = 96
        confirm.loc[closed_index, "ema50"] = 100
        confirm.loc[closed_index, "session_vwap"] = 100
        confirm.loc[closed_index, "macd_hist"] = -0.5

        with patch(
            "strategy.detect_market_structure",
            return_value={"bearish_breakdown": True},
        ):
            health = _trend_health_context("BUY", trend, confirm)

        self.assertTrue(health["hard_failure"])
        self.assertFalse(health["healthy"])

    def test_intraday_candidate_requests_and_prioritizes_futures_context(self):
        intraday = {
            "eligible": True,
            "active": False,
            "participation_available": False,
        }
        side = {
            "side": "BUY",
            "trend_confidence": 82,
            "quality_score": 1,
            "smc_score": 1,
            "regime_score": 1,
            "intraday_entry": intraday,
        }
        analysis = {
            "best_confidence": 82,
            "buy": side,
            "sell": {},
        }

        with patch.object(config, "FUTURES_CONTEXT_ENABLED", True), patch.object(
            config,
            "FUTURES_CONTEXT_MIN_CONFIDENCE",
            60,
        ), patch.object(
            config,
            "FUTURES_CONTEXT_PRIORITY_INTRADAY_BONUS",
            8,
        ):
            self.assertTrue(should_fetch_futures_context(analysis))
            intraday_priority = futures_context_priority(analysis)
            normal_priority = futures_context_priority({
                **analysis,
                "buy": {
                    **side,
                    "intraday_entry": {"eligible": False},
                },
            })

        self.assertEqual(intraday_priority - normal_priority, 8)


if __name__ == "__main__":
    unittest.main()
