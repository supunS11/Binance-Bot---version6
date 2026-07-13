import unittest
from unittest.mock import patch

import config
from backtest import apply_position_limits


def trade(side, confirmation_type, entry_ms, exit_ms):
    return {
        "side": side,
        "confirmation_type": confirmation_type,
        "entry_ms": entry_ms,
        "exit_ms": exit_ms,
    }


class BacktestPositionLimitTests(unittest.TestCase):
    def test_trend_and_reversal_use_separate_position_pools(self):
        trades = [
            trade("BUY", "TREND", 1, 10),
            trade("SELL", "REVERSAL", 2, 10),
            trade("SELL", "TREND", 3, 10),
            trade("BUY", "REVERSAL", 4, 10),
        ]

        with (
            patch.object(config, "BACKTEST_APPLY_POSITION_LIMITS", True),
            patch.object(config, "MAX_TOTAL_POSITIONS", 1),
            patch.object(config, "MAX_BUY_POSITIONS", 1),
            patch.object(config, "MAX_SELL_POSITIONS", 1),
            patch.object(config, "REVERSAL_EXTRA_TOTAL_POSITIONS", 1),
            patch.object(config, "REVERSAL_EXTRA_BUY_POSITIONS", 1),
            patch.object(config, "REVERSAL_EXTRA_SELL_POSITIONS", 1),
        ):
            accepted, skipped = apply_position_limits(trades)

        self.assertEqual(len(accepted), 2)
        self.assertEqual(skipped, 2)
        self.assertEqual(
            {item["confirmation_type"] for item in accepted},
            {"TREND", "REVERSAL"},
        )

    def test_zero_reversal_limit_disables_reversal_pool(self):
        trades = [trade("BUY", "REVERSAL", 1, 10)]

        with (
            patch.object(config, "BACKTEST_APPLY_POSITION_LIMITS", True),
            patch.object(config, "REVERSAL_EXTRA_TOTAL_POSITIONS", 0),
            patch.object(config, "REVERSAL_EXTRA_BUY_POSITIONS", 0),
            patch.object(config, "REVERSAL_EXTRA_SELL_POSITIONS", 0),
        ):
            accepted, skipped = apply_position_limits(trades)

        self.assertEqual(accepted, [])
        self.assertEqual(skipped, 1)


if __name__ == "__main__":
    unittest.main()
