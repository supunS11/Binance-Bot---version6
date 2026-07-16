import unittest

import pandas as pd

from indicators import apply_indicators


class IntradayIndicatorTests(unittest.TestCase):
    def test_intraday_context_columns_are_calculated(self):
        start_ms = 1_752_825_600_000
        rows = []

        for index in range(320):
            close = 100 + (index * 0.08)
            rows.append({
                "time": start_ms + (index * 15 * 60_000),
                "open": close - 0.04,
                "high": close + 0.25,
                "low": close - 0.25,
                "close": close,
                "volume": 100 + (index % 12),
            })

        result = apply_indicators(pd.DataFrame(rows))

        self.assertIsNotNone(result)
        self.assertGreater(len(result), 50)

        for column in (
            "macd_hist",
            "plus_di",
            "minus_di",
            "di_spread",
            "adx_slope",
            "efficiency_ratio",
            "volume_ratio",
            "session_vwap",
            "atr_pct",
        ):
            self.assertIn(column, result.columns)
            self.assertFalse(result[column].isna().any())

        self.assertGreater(float(result.iloc[-1]["efficiency_ratio"]), 0.8)
        self.assertGreater(float(result.iloc[-1]["session_vwap"]), 0)


if __name__ == "__main__":
    unittest.main()
