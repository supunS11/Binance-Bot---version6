import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import config


with patch("binance.client.Client.ping", return_value={}), patch(
    "binance.client.Client.get_server_time",
    return_value={"serverTime": 0},
):
    import main
    import trade_state


SYMBOL = "TESTUSDT"


def pending_execution(**updates):
    pending = {
        "symbol": SYMBOL,
        "side": "BUY",
        "context": "ENTRY",
        "requested_quantity": 1.0,
        "pre_position_amount": 0.0,
        "reference_price": 100.0,
        "position_side": "BOTH",
        "signal_type": "TREND",
        "dca_level": None,
        "client_order_ids": "cid-ioc,cid-market",
        "order_ids": "",
        "execution_mode": "SMART_IOC_MARKET_FALLBACK",
        "emergency_protection_secured": False,
    }
    pending.update(updates)
    return pending


def terminal_result(terminal):
    return {
        "order_terminal": terminal,
        "orders": [],
        "executed_quantity": 0.0,
        "average_fill_price": 0.0,
        "order_ids": "",
        "client_order_ids": "cid-ioc,cid-market",
        "verification_attempts": 1,
        "error": "" if terminal else "status unavailable",
    }


def persist_in_memory(state, symbol, data):
    state.setdefault("pending_executions", {})[symbol] = data
    return True


def remove_in_memory(state, symbol):
    state.setdefault("pending_executions", {}).pop(symbol, None)
    return True


class PendingExecutionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self._state_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._state_directory.cleanup)
        state_path = Path(self._state_directory.name) / "trade_state.json"
        state_path_patch = patch.object(config, "DCA_STATE_PATH", str(state_path))
        state_path_patch.start()
        self.addCleanup(state_path_patch.stop)
        known_symbol_patch = patch(
            "main.is_known_futures_symbol",
            return_value=True,
        )
        known_symbol_patch.start()
        self.addCleanup(known_symbol_patch.stop)
        main.entry_quarantined_symbols.discard(SYMBOL)
        self.addCleanup(main.entry_quarantined_symbols.discard, SYMBOL)

    def test_nonterminal_no_fill_stays_pending_without_close_or_new_order(self):
        state = {
            "positions": {},
            "pending_executions": {SYMBOL: pending_execution()},
        }

        with patch(
            "main.reconcile_execution_client_orders",
            return_value=terminal_result(False),
        ) as reconcile, patch(
            "main._pending_execution_live_detail",
            return_value=(True, None),
        ), patch(
            "main.upsert_pending_execution",
            side_effect=persist_in_memory,
        ) as upsert, patch(
            "main._secure_pending_execution_protection",
        ) as protect, patch(
            "main.fail_safe_close_unprotected_position",
        ) as fail_safe_close, patch(
            "main.place_market_order",
        ) as new_order, patch("main.log_error"):
            main.reconcile_pending_executions(state, position_details={})

        reconcile.assert_called_once_with(
            SYMBOL,
            "cid-ioc,cid-market",
            cancel_unsettled=True,
        )
        upsert.assert_called_once()
        protect.assert_not_called()
        fail_safe_close.assert_not_called()
        new_order.assert_not_called()
        self.assertIn(SYMBOL, state["pending_executions"])
        self.assertEqual(
            state["pending_executions"][SYMBOL]["observed_position_delta"],
            0,
        )

    def test_nonterminal_visible_fill_gets_emergency_full_position_protection(self):
        pending = pending_execution()
        state = {
            "positions": {},
            "pending_executions": {SYMBOL: pending},
        }
        live_detail = {
            "amount": 0.4,
            "side": "BUY",
            "position_side": "BOTH",
            "entry_price": 101.0,
            "mark_price": 102.0,
        }
        protection = {
            "ok": True,
            "tp_price": 111.0,
            "sl_price": 96.0,
        }

        with patch(
            "main.reconcile_execution_client_orders",
            return_value=terminal_result(False),
        ), patch(
            "main._pending_execution_live_detail",
            return_value=(True, live_detail),
        ), patch(
            "main.get_signal_frames",
            return_value=(Mock(), Mock(), Mock()),
        ), patch(
            "main.place_tp_sl_with_recovery",
            return_value=protection,
        ) as place_protection, patch(
            "main.upsert_pending_execution",
            side_effect=persist_in_memory,
        ) as upsert, patch(
            "main.fail_safe_close_unprotected_position",
        ) as fail_safe_close, patch(
            "main.place_market_order",
        ) as new_order, patch("main.log_error"):
            main.reconcile_pending_executions(
                state,
                position_details={SYMBOL: live_detail},
            )

        place_protection.assert_called_once()
        args = place_protection.call_args.args
        self.assertEqual(args[:4], (SYMBOL, main.SIDE_BUY, 101.0, 0.4))
        self.assertFalse(place_protection.call_args.kwargs["enable_multi_tp"])
        self.assertEqual(
            place_protection.call_args.kwargs["position_side"],
            "BOTH",
        )
        upsert.assert_called_once()
        fail_safe_close.assert_not_called()
        new_order.assert_not_called()
        recovered = state["pending_executions"][SYMBOL]
        self.assertTrue(recovered["emergency_protection_secured"])
        self.assertEqual(
            recovered["emergency_protection_mode"],
            "FULL_POSITION_TP_SL",
        )
        self.assertEqual(recovered["emergency_tp_price"], 111.0)
        self.assertEqual(recovered["emergency_sl_price"], 96.0)

    def test_terminal_no_new_fill_clears_pending_and_dca_reservation(self):
        pending = pending_execution(
            context="DCA_LEVEL_2",
            dca_level=2,
            pre_position_amount=1.0,
        )
        state = {
            "positions": {
                SYMBOL: {
                    "managed_by_bot": True,
                    "pending_dca": {
                        "level": 2,
                        "execution_unsettled": True,
                    },
                },
            },
            "pending_executions": {SYMBOL: pending},
        }
        unchanged_position = {
            "amount": 1.0,
            "side": "BUY",
            "position_side": "BOTH",
            "entry_price": 100.0,
            "mark_price": 100.0,
        }

        def clear_reservation(current_state, symbol, level=None):
            item = current_state["positions"][symbol]
            if level == item.get("pending_dca", {}).get("level"):
                item.pop("pending_dca", None)

        with patch(
            "main.reconcile_execution_client_orders",
            return_value=terminal_result(True),
        ), patch(
            "main._pending_execution_live_detail",
            return_value=(True, unchanged_position),
        ), patch(
            "main._secure_pending_execution_protection",
            return_value=True,
        ) as secure_protection, patch(
            "main.clear_dca_reservation",
            side_effect=clear_reservation,
        ) as clear_dca, patch(
            "main.remove_pending_execution",
            side_effect=remove_in_memory,
        ) as remove_pending, patch(
            "main.fail_safe_close_unprotected_position",
        ) as fail_safe_close, patch("main.log_warning"):
            main.reconcile_pending_executions(
                state,
                position_details={SYMBOL: unchanged_position},
            )

        secure_protection.assert_called_once_with(
            state,
            SYMBOL,
            pending,
            unchanged_position,
        )
        clear_dca.assert_called_once_with(state, SYMBOL, 2)
        remove_pending.assert_called_once_with(state, SYMBOL)
        fail_safe_close.assert_not_called()
        self.assertNotIn("pending_dca", state["positions"][SYMBOL])
        self.assertNotIn(SYMBOL, state["pending_executions"])

    def test_terminal_late_fill_is_fail_safe_closed_before_pending_is_cleared(self):
        state = {
            "positions": {},
            "pending_executions": {SYMBOL: pending_execution()},
        }
        late_position = {
            "amount": 0.25,
            "side": "BUY",
            "position_side": "BOTH",
            "entry_price": 100.5,
            "mark_price": 101.0,
        }

        with patch(
            "main.reconcile_execution_client_orders",
            return_value=terminal_result(True),
        ), patch(
            "main._pending_execution_live_detail",
            return_value=(True, late_position),
        ), patch(
            "main.fail_safe_close_unprotected_position",
            return_value=True,
        ) as fail_safe_close, patch(
            "main.remove_pending_execution",
            side_effect=remove_in_memory,
        ) as remove_pending, patch(
            "main._secure_pending_execution_protection",
        ) as protect, patch("main.log_warning"):
            main.reconcile_pending_executions(
                state,
                position_details={SYMBOL: late_position},
            )

        fail_safe_close.assert_called_once_with(
            SYMBOL,
            position_side="BOTH",
            reference_price=101.0,
            context="ENTRY_LATE_RECONCILIATION",
        )
        remove_pending.assert_called_once_with(state, SYMBOL)
        protect.assert_not_called()
        self.assertNotIn(SYMBOL, state["pending_executions"])

    def test_unknown_flat_symbol_clears_reservation_then_pending_without_rest(self):
        pending = pending_execution(
            context="DCA_LEVEL_2",
            dca_level=2,
            pre_position_amount=1.0,
        )
        state = {
            "positions": {
                SYMBOL: {
                    "managed_by_bot": True,
                    "pending_dca": {"level": 2, "execution_unsettled": True},
                },
            },
            "pending_executions": {SYMBOL: pending},
        }

        events = []

        def clear_reservation(current_state, symbol, level=None):
            events.append(("clear", symbol, level))
            current_state["positions"][symbol].pop("pending_dca", None)
            return True

        def remove_pending(current_state, symbol):
            events.append(("remove", symbol))
            return remove_in_memory(current_state, symbol)

        with patch(
            "main.is_known_futures_symbol",
            return_value=False,
        ), patch(
            "main.clear_dca_reservation",
            side_effect=clear_reservation,
        ), patch(
            "main.remove_pending_execution",
            side_effect=remove_pending,
        ), patch(
            "main.reconcile_execution_client_orders",
        ) as reconcile, patch(
            "main._pending_execution_live_detail",
        ) as live_detail, patch(
            "main._secure_pending_execution_protection",
        ) as protect, patch(
            "main.cancel_open_protection_orders",
        ) as cancel_protection, patch("main.log_warning"):
            main.reconcile_pending_executions(state, position_details={})

        self.assertEqual(
            events,
            [("clear", SYMBOL, 2), ("remove", SYMBOL)],
        )
        self.assertNotIn(SYMBOL, state["pending_executions"])
        self.assertNotIn("pending_dca", state["positions"][SYMBOL])
        self.assertNotIn(SYMBOL, main.entry_quarantined_symbols)
        reconcile.assert_not_called()
        live_detail.assert_not_called()
        protect.assert_not_called()
        cancel_protection.assert_not_called()

    def test_catalog_unavailable_retains_and_quarantines_without_private_rest(self):
        state = {
            "positions": {},
            "pending_executions": {SYMBOL: pending_execution()},
        }

        with patch(
            "main.is_known_futures_symbol",
            return_value=None,
        ), patch(
            "main.remove_pending_execution",
        ) as remove_pending, patch(
            "main.reconcile_execution_client_orders",
        ) as reconcile, patch(
            "main._pending_execution_live_detail",
        ) as live_detail, patch("main.log_error"):
            main.reconcile_pending_executions(state, position_details={})

        self.assertIn(SYMBOL, state["pending_executions"])
        self.assertIn(SYMBOL, main.entry_quarantined_symbols)
        remove_pending.assert_not_called()
        reconcile.assert_not_called()
        live_detail.assert_not_called()

    def test_unknown_symbol_with_live_global_row_is_retained_without_private_rest(self):
        state = {
            "positions": {},
            "pending_executions": {SYMBOL: pending_execution()},
        }
        global_detail = {"symbol": SYMBOL, "amount": 1.0}

        with patch(
            "main.is_known_futures_symbol",
            return_value=False,
        ), patch(
            "main.remove_pending_execution",
        ) as remove_pending, patch(
            "main.reconcile_execution_client_orders",
        ) as reconcile, patch(
            "main._pending_execution_live_detail",
        ) as live_detail, patch("main.log_error"):
            main.reconcile_pending_executions(
                state,
                position_details={SYMBOL: global_detail},
            )

        self.assertIn(SYMBOL, state["pending_executions"])
        self.assertIn(SYMBOL, main.entry_quarantined_symbols)
        remove_pending.assert_not_called()
        reconcile.assert_not_called()
        live_detail.assert_not_called()

    def test_unknown_symbol_matches_normalized_global_snapshot_key(self):
        state = {
            "positions": {},
            "pending_executions": {SYMBOL: pending_execution()},
        }

        with patch(
            "main.is_known_futures_symbol",
            return_value=False,
        ), patch(
            "main.remove_pending_execution",
        ) as remove_pending, patch(
            "main.reconcile_execution_client_orders",
        ) as reconcile, patch("main.log_error"):
            main.reconcile_pending_executions(
                state,
                position_details={SYMBOL.lower(): {"amount": 1.0}},
            )

        self.assertIn(SYMBOL, state["pending_executions"])
        self.assertIn(SYMBOL, main.entry_quarantined_symbols)
        remove_pending.assert_not_called()
        reconcile.assert_not_called()

    def test_unknown_symbol_retains_when_global_snapshot_is_unavailable(self):
        state = {
            "positions": {},
            "pending_executions": {SYMBOL: pending_execution()},
        }

        with patch(
            "main.get_open_position_details",
            return_value=None,
        ) as snapshot, patch(
            "main.is_known_futures_symbol",
            return_value=False,
        ) as known_symbol, patch(
            "main.remove_pending_execution",
        ) as remove_pending, patch(
            "main.reconcile_execution_client_orders",
        ) as reconcile, patch("main.log_error"):
            main.reconcile_pending_executions(state)

        snapshot.assert_called_once_with(force=True)
        known_symbol.assert_called_once_with(SYMBOL)
        remove_pending.assert_not_called()
        reconcile.assert_not_called()
        self.assertIn(SYMBOL, state["pending_executions"])
        self.assertIn(SYMBOL, main.entry_quarantined_symbols)

    def test_unknown_dca_symbol_retains_when_reservation_cleanup_fails(self):
        state = {
            "positions": {},
            "pending_executions": {
                SYMBOL: pending_execution(context="DCA_LEVEL_2", dca_level=2),
            },
        }

        with patch(
            "main.is_known_futures_symbol",
            return_value=False,
        ), patch(
            "main.clear_dca_reservation",
            return_value=False,
        ) as clear_reservation, patch(
            "main.remove_pending_execution",
        ) as remove_pending, patch(
            "main.reconcile_execution_client_orders",
        ) as reconcile, patch("main.log_error"):
            main.reconcile_pending_executions(state, position_details={})

        clear_reservation.assert_called_once_with(state, SYMBOL, 2)
        remove_pending.assert_not_called()
        reconcile.assert_not_called()
        self.assertIn(SYMBOL, state["pending_executions"])
        self.assertIn(SYMBOL, main.entry_quarantined_symbols)

    def test_unknown_dca_with_missing_level_never_clears_existing_reservation(self):
        state = {
            "positions": {
                SYMBOL: {
                    "managed_by_bot": True,
                    "pending_dca": {"level": 2, "execution_unsettled": True},
                },
            },
            "pending_executions": {
                SYMBOL: pending_execution(context="DCA_RECOVERY", dca_level=None),
            },
        }

        with patch(
            "main.is_known_futures_symbol",
            return_value=False,
        ), patch(
            "main.clear_dca_reservation",
        ) as clear_reservation, patch(
            "main.remove_pending_execution",
        ) as remove_pending, patch(
            "main.reconcile_execution_client_orders",
        ) as reconcile, patch("main.log_error"):
            main.reconcile_pending_executions(state, position_details={})

        clear_reservation.assert_not_called()
        remove_pending.assert_not_called()
        reconcile.assert_not_called()
        self.assertIn("pending_dca", state["positions"][SYMBOL])
        self.assertIn(SYMBOL, state["pending_executions"])
        self.assertIn(SYMBOL, main.entry_quarantined_symbols)

    def test_unknown_dca_without_level_or_reservation_removes_only_pending_marker(self):
        state = {
            "positions": {},
            "pending_executions": {
                SYMBOL: pending_execution(context="DCA_RECOVERY", dca_level=None),
            },
        }

        with patch(
            "main.is_known_futures_symbol",
            return_value=False,
        ), patch(
            "main.clear_dca_reservation",
        ) as clear_reservation, patch(
            "main.remove_pending_execution",
            side_effect=remove_in_memory,
        ) as remove_pending, patch(
            "main.reconcile_execution_client_orders",
        ) as reconcile, patch("main.log_warning"):
            main.reconcile_pending_executions(state, position_details={})

        clear_reservation.assert_not_called()
        remove_pending.assert_called_once_with(state, SYMBOL)
        reconcile.assert_not_called()
        self.assertNotIn(SYMBOL, state["pending_executions"])

    def test_unknown_symbol_retains_when_pending_remove_is_not_durable(self):
        state = {
            "positions": {},
            "pending_executions": {SYMBOL: pending_execution()},
        }

        with patch(
            "main.is_known_futures_symbol",
            return_value=False,
        ), patch(
            "main.remove_pending_execution",
            return_value=False,
        ) as remove_pending, patch(
            "main.reconcile_execution_client_orders",
        ) as reconcile, patch("main.log_error"):
            main.reconcile_pending_executions(state, position_details={})

        remove_pending.assert_called_once_with(state, SYMBOL)
        reconcile.assert_not_called()
        self.assertIn(SYMBOL, state["pending_executions"])
        self.assertIn(SYMBOL, main.entry_quarantined_symbols)

    def test_entry_guard_blocks_symbol_with_pending_execution(self):
        pending = pending_execution()
        state = {
            "positions": {},
            "pending_executions": {SYMBOL: pending},
        }
        candidate = {
            "symbol": SYMBOL,
            "signal": "BUY",
            "analysis": {},
            "participation": None,
            "trend_df": None,
            "confirm_df": None,
            "entry_df": None,
            "btc_trend": None,
            "btc_corr": None,
            "rs": None,
            "news_context": None,
            "llm_context": None,
        }
        position_details = {}
        open_positions = {}

        with patch.object(
            main.shutdown_event,
            "is_set",
            return_value=False,
        ), patch("main.place_market_order") as place_order, patch(
            "main.market_flow_hard_veto",
        ) as flow_veto, patch("main.log_warning"):
            result = main.execute_entry_candidate(
                candidate,
                state,
                position_details,
                open_positions,
                None,
                Mock(),
            )

        self.assertEqual(result, (position_details, open_positions, False))
        place_order.assert_not_called()
        flow_veto.assert_not_called()

    def test_dca_guard_blocks_symbol_with_pending_execution(self):
        state = {
            "positions": {
                SYMBOL: {
                    "managed_by_bot": True,
                    "side": "BUY",
                    "dca_count": 0,
                },
            },
            "pending_executions": {SYMBOL: pending_execution()},
        }
        position_detail = {
            "amount": 1.0,
            "side": "BUY",
            "position_side": "BOTH",
            "entry_price": 100.0,
        }

        with patch.object(config, "DCA_ENABLED", True), patch.object(
            config,
            "DCA_FIXED_RISK_ENABLED",
            False,
        ), patch.object(
            config,
            "POSITION_MANAGEMENT_LEGACY_ENABLED",
            True,
        ), patch.object(
            main.shutdown_event,
            "is_set",
            return_value=False,
        ), patch("main.place_market_order") as place_order, patch(
            "main.get_signal_frames",
        ) as get_frames, patch("main.log_warning"):
            main.manage_dca_position(
                SYMBOL,
                state,
                position_detail,
                None,
                None,
            )

        place_order.assert_not_called()
        get_frames.assert_not_called()


class PendingExecutionStatePersistenceTests(unittest.TestCase):
    def test_pending_execution_upsert_and_remove_are_durable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "trade_state.json"
            state = {"positions": {}, "pending_executions": {}}
            pending = pending_execution()

            with patch.object(
                config,
                "DCA_STATE_PATH",
                str(state_path),
            ), patch.object(
                config,
                "STATE_UPSERT_RETRY_ATTEMPTS",
                1,
                create=True,
            ), patch.object(
                config,
                "STATE_UPSERT_RETRY_DELAY_SECONDS",
                0,
                create=True,
            ):
                self.assertTrue(
                    trade_state.upsert_pending_execution(
                        state,
                        SYMBOL,
                        pending,
                    )
                )
                persisted = trade_state.load_trade_state()
                self.assertEqual(
                    persisted["pending_executions"][SYMBOL][
                        "client_order_ids"
                    ],
                    "cid-ioc,cid-market",
                )

                self.assertTrue(
                    trade_state.remove_pending_execution(state, SYMBOL)
                )
                persisted = trade_state.load_trade_state()
                self.assertNotIn(SYMBOL, persisted["pending_executions"])


if __name__ == "__main__":
    unittest.main()
