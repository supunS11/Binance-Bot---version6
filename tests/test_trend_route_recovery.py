import unittest
from unittest.mock import patch

import config
from strategy import (
    _trend_route_recovery_context,
    futures_context_priority,
    should_fetch_futures_context,
)


def build_context(**overrides):
    values = {
        "normal_trend_following_ok": True,
        "trend_timing_rescue": {"eligible": False, "active": False},
        "continuation_pullback": {"eligible": False, "active": False},
        "legacy_trend_following_ok": True,
        "trend_confidence": 82,
        "participation_score": 1.0,
        "participation": {"available": True},
        "futures_ok": True,
    }
    values.update(overrides)
    return _trend_route_recovery_context(**values)


class TrendRouteRecoveryTests(unittest.TestCase):
    def config_patches(self):
        return (
            patch.object(config, "TREND_ROUTE_RECOVERY_ENABLED", True),
            patch.object(config, "TREND_ROUTE_RECOVERY_MIN_CONFIDENCE", 78),
            patch.object(config, "TREND_ROUTE_RECOVERY_REQUIRE_FUTURES", True),
            patch.object(config, "TREND_ROUTE_RECOVERY_MIN_FUTURES_SCORE", 0.5),
        )

    def test_qualified_route_waits_for_futures_context(self):
        patches = self.config_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            result = build_context(
                participation=None,
                participation_score=0,
            )

        self.assertTrue(result["eligible"])
        self.assertFalse(result["active"])
        self.assertEqual(
            result["reason"],
            "TREND_ROUTE_RECOVERY_AWAITING_FUTURES",
        )

    def test_supportive_futures_activates_qualified_route(self):
        patches = self.config_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            result = build_context()

        self.assertTrue(result["eligible"])
        self.assertTrue(result["active"])
        self.assertEqual(result["source"], "NORMAL_TREND")

    def test_conflicting_futures_blocks_recovery(self):
        patches = self.config_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            result = build_context(participation_score=0.25)

        self.assertTrue(result["eligible"])
        self.assertFalse(result["active"])
        self.assertIn("FUTURES_SCORE=0.25 < 0.5", result["reasons"])

    def test_low_confidence_route_is_not_recovered(self):
        patches = self.config_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            result = build_context(trend_confidence=77.99)

        self.assertFalse(result["eligible"])
        self.assertFalse(result["active"])

    def test_waiting_recovery_requests_and_prioritizes_futures(self):
        patches = self.config_patches()
        with patches[0], patches[1], patches[2], patches[3], patch.object(
            config,
            "FUTURES_CONTEXT_ENABLED",
            True,
        ), patch.object(
            config,
            "FUTURES_CONTEXT_MIN_CONFIDENCE",
            60,
        ), patch.object(
            config,
            "FUTURES_CONTEXT_PRIORITY_TREND_RECOVERY_BONUS",
            8,
        ):
            waiting = build_context(
                participation=None,
                participation_score=0,
            )
            analysis = {
                "best_confidence": 82,
                "buy": {
                    "side": "BUY",
                    "trend_confidence": 82,
                    "quality_score": 1,
                    "smc_score": 1,
                    "regime_score": 0,
                    "trend_route_recovery": waiting,
                },
                "sell": {},
            }
            self.assertTrue(should_fetch_futures_context(analysis))
            recovery_priority = futures_context_priority(analysis)
            analysis["buy"]["trend_route_recovery"] = {"eligible": False}
            base_priority = futures_context_priority(analysis)

        self.assertEqual(recovery_priority - base_priority, 8)


if __name__ == "__main__":
    unittest.main()
