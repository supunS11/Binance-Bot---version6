import unittest
from unittest.mock import patch

import config
from strategy import validate_dca_continuation_guard


class DcaContinuationGuardTests(unittest.TestCase):
    def evaluate(self, structure_ok):
        with (
            patch.object(config, "DCA_STRICT_GUARD_ENABLED", True),
            patch.object(
                config,
                "DCA_STRICT_GUARD_APPLY_TO_REVERSAL_ONLY",
                False,
            ),
            patch.object(
                config,
                "DCA_STRICT_GUARD_STRUCTURE_CHECK_ENABLED",
                True,
            ),
            patch.object(
                config,
                "DCA_STRICT_GUARD_BLOCK_TREND_ON_NO_STRUCTURE",
                True,
            ),
            patch(
                "strategy._continuation_pressure_against_side",
                return_value={"score": 0},
            ),
            patch(
                "strategy._reversal_recovery_score",
                return_value={"score": 3},
            ),
            patch(
                "strategy.validate_dca_structure_level",
                return_value=(
                    structure_ok,
                    {
                        "reason": (
                            "DCA_STRUCTURE_OK"
                            if structure_ok
                            else "NO_DCA_STRUCTURE"
                        )
                    },
                ),
            ),
        ):
            return validate_dca_continuation_guard(
                "BUY",
                current_price=95,
                avg_entry=100,
                trend_df=object(),
                confirm_df=object(),
                entry_df=object(),
                leverage=10,
                confirmation_type="TREND",
                dca_level=1,
                adverse_roi=50,
                position_adverse_roi=50,
            )

    def test_trend_dca_is_blocked_without_supporting_structure(self):
        allowed, info = self.evaluate(structure_ok=False)

        self.assertFalse(allowed)
        self.assertEqual(info["reason"], "NO_DCA_STRUCTURE")

    def test_trend_dca_remains_allowed_with_supporting_structure(self):
        allowed, info = self.evaluate(structure_ok=True)

        self.assertTrue(allowed)
        self.assertEqual(info["reason"], "DCA_STRICT_GUARD_OK")


if __name__ == "__main__":
    unittest.main()
