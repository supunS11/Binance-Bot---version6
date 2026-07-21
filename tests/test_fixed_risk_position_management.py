import unittest
from unittest.mock import patch

import pandas as pd

import config
import main
import risk_management
import strategy


class FixedRiskSizingTests(unittest.TestCase):
    def test_position_risk_cap_limits_campaign_quantity(self):
        """The dollar cap wins when percentage risk would be larger."""
        with patch.object(
            config,
            "RISK_BASED_POSITION_SIZING_ENABLED",
            True,
        ), patch.object(config, "POSITION_RISK_PCT", 1.0), patch.object(
            config,
            "POSITION_RISK_MAX_USDT",
            5.0,
        ), patch.object(config, "MARGIN_PER_TRADE", 100.0), patch.object(
            config,
            "LEVERAGE",
            1,
        ), patch(
            "risk_management.get_symbol_precision",
            return_value=3,
        ):
            quantity = risk_management.calculate_position_size(
                balance=1000.0,
                entry_price=100.0,
                sl_price=90.0,
                symbol="BTCUSDT",
            )

        self.assertEqual(quantity, 0.5)
        self.assertLessEqual(quantity * 10.0, 5.0)

    def test_fixed_risk_quantity_is_floored_not_rounded_up(self):
        with patch.object(
            config,
            "RISK_BASED_POSITION_SIZING_ENABLED",
            True,
        ), patch.object(config, "MARGIN_PER_TRADE", 100.0), patch.object(
            config,
            "LEVERAGE",
            1,
        ), patch(
            "risk_management.get_symbol_precision",
            return_value=3,
        ):
            quantity = risk_management.calculate_position_size(
                balance=1000.0,
                entry_price=100.0,
                sl_price=98.7,
                symbol="BTCUSDT",
                risk_budget_override=1.0,
            )

        self.assertEqual(quantity, 0.769)
        self.assertLessEqual(quantity * 1.3, 1.0)

    def test_min_notional_does_not_force_risk_above_budget(self):
        with patch.object(
            config,
            "RISK_BASED_POSITION_SIZING_ENABLED",
            True,
        ), patch.object(config, "MARGIN_PER_TRADE", 100.0), patch.object(
            config,
            "LEVERAGE",
            1,
        ), patch(
            "risk_management.get_symbol_precision",
            return_value=3,
        ):
            quantity = risk_management.calculate_position_size(
                balance=1000.0,
                entry_price=100.0,
                sl_price=90.0,
                symbol="BTCUSDT",
                risk_budget_override=0.49,
            )

        self.assertEqual(quantity, 0)


class FixedRiskRecoveryAndTimeExitTests(unittest.TestCase):
    def test_stop_buffer_roi_is_numeric_for_both_sides(self):
        with patch.object(config, "LEVERAGE", 10):
            self.assertEqual(main.get_stop_buffer_roi("BUY", 100.0, 96.0), 40.0)
            self.assertEqual(main.get_stop_buffer_roi("SELL", 100.0, 104.0), 40.0)
            self.assertEqual(main.get_stop_buffer_roi("BUY", 100.0, 101.0), 0)

    def test_armed_recovery_keeps_websocket_ticks_during_rebound(self):
        state = {
            "positions": {
                "BTCUSDT": {
                    "managed_by_bot": True,
                    "side": "BUY",
                    "avg_entry": 100.0,
                    "initial_entry": 100.0,
                    "dca_count": 0,
                    "dca_recovery_status": "ARMED",
                    "dca_recovery_level": 1,
                    "position_management_status": "ACTIVE",
                }
            }
        }

        with patch.object(config, "DCA_MAX_ORDERS", 1), patch.object(
            config,
            "DCA_TRIGGER_ROIS",
            [25.0],
        ):
            # At 10x leverage this mark is only about -10% ROI, already back
            # above the -25% arming threshold, but it still needs live ticks so
            # the rebound confirmation can complete.
            self.assertTrue(main.dca_tick_ready("BTCUSDT", 99.0, state=state))

    def test_recovery_confirmation_uses_v6_live_5m_and_15m_frames(self):
        supportive = {
            "supports_direction": True,
            "opposes_direction": False,
            "structure_break": False,
            "opposite_reversal": False,
        }

        with patch.object(
            config,
            "DCA_RECOVERY_CONFIRMATION_ENABLED",
            True,
        ), patch.object(
            config,
            "DCA_RECOVERY_REQUIRE_BOTH_TIMEFRAMES",
            True,
        ), patch.object(config, "LIVE_ENTRY_FAST_TIMEFRAME", "5m"), patch.object(
            config,
            "LIVE_ENTRY_SLOW_TIMEFRAME",
            "15m",
        ), patch(
            "strategy._live_entry_timeframe_check",
            side_effect=[supportive, supportive],
        ) as timeframe_check:
            allowed, details = strategy.validate_dca_recovery_confirmation(
                "BUY",
                fast_df=object(),
                slow_df=object(),
                mark_price=100.0,
            )

        self.assertTrue(allowed)
        self.assertEqual(details["reason"], "DCA_RECOVERY_CONFIRMED")
        self.assertEqual(details["required_support"], 2)
        self.assertEqual(
            [call.args[3] for call in timeframe_check.call_args_list],
            ["5m", "15m"],
        )

    def test_time_exit_evidence_uses_v6_confirmation_and_trend_labels(self):
        # The penultimate row is the latest closed candle in the strategy.
        trend_df = pd.DataFrame([
            {
                "close": 101.0,
                "ema20": 101.0,
                "ema50": 100.0,
                "macd": 0.2,
                "macd_signal": 0.1,
                "high": 102.0,
                "low": 99.0,
            },
            {
                "close": 95.0,
                "ema20": 97.0,
                "ema50": 100.0,
                "macd": -0.5,
                "macd_signal": 0.2,
                "high": 98.0,
                "low": 94.0,
            },
            {
                "close": 96.0,
                "ema20": 97.0,
                "ema50": 100.0,
                "macd": -0.4,
                "macd_signal": 0.1,
                "high": 97.0,
                "low": 94.0,
            },
        ])
        confirm_df = pd.DataFrame([
            {
                "close": 100.0,
                "ema20": 100.0,
                "ema50": 99.0,
                "macd": 0.3,
                "macd_signal": 0.2,
                "high": 101.0,
                "low": 98.0,
            },
            {
                "close": 95.0,
                "ema20": 97.0,
                "ema50": 99.0,
                "macd": -0.5,
                "macd_signal": 0.2,
                "high": 97.0,
                "low": 94.0,
            },
            {
                "close": 96.0,
                "ema20": 97.0,
                "ema50": 99.0,
                "macd": -0.4,
                "macd_signal": 0.1,
                "high": 97.0,
                "low": 94.0,
            },
        ])

        with patch.object(config, "TREND_TIMEFRAME", "1h"), patch.object(
            config,
            "CONFIRMATION_TIMEFRAME",
            "30m",
        ), patch.object(config, "TIME_EXIT_MIN_WEAKNESS_SCORE", 2):
            result = strategy.evaluate_time_exit_weakness(
                "BUY",
                trend_df,
                confirm_df,
            )

        self.assertTrue(result["should_exit"])
        self.assertEqual(result["reason"], "TIME_EXIT_TREND_WEAKENED")
        self.assertIn("30M_CLOSE_BELOW_EMA20", result["evidence"])
        self.assertIn("30M_STRUCTURE_BREAK", result["evidence"])
        self.assertIn("1H_CLOSE_BELOW_EMA50", result["evidence"])
        self.assertNotIn("4H_CLOSE_BELOW_EMA20", result["evidence"])
        self.assertNotIn("1D_CLOSE_BELOW_EMA50", result["evidence"])


if __name__ == "__main__":
    unittest.main()
