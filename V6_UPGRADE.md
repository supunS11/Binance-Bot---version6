# v6 execution, fixed-risk recovery, and TP runner upgrade

## Included

- Exact client-order fill reconciliation, residual tracking, slippage, fee, and
  latency telemetry.
- Marketable IOC entry/DCA execution with market fallback only after the IOC is
  confirmed terminal.
- CVD, footprint, and retained top-1000 depth analytics in observation-only
  shadow mode. Shadow output does not change rank, filters, sizing, or execution.
- TP1 75% lifecycle hardening: exact triggered-child fill attribution, persisted
  repair intent, restart adoption, runner SL placement before TP2, and stale-order
  reconciliation.
- One fixed-risk recovery add replaces the averaging ladder for newly opened V6
  campaigns. The add first arms at the adverse-ROI trigger, then requires an
  actual rebound plus agreement from V6's existing 5m and 15m live frames.
- One immutable exchange hard stop, confirmed early invalidation, and a
  weakness-confirmed time stop share one durable exit owner so they cannot race
  DCA, TP1/TP2, or profit protection.
- Risk sizing applies to the complete initial-plus-recovery campaign. The
  configured margin is a ceiling, not a promise to consume all available margin.
- Fail-closed one-way-mode and runtime-state validation, rolling state backup,
  graceful SIGINT/SIGTERM cleanup, and explicit execution-telemetry flushing.

The v6 strategy timeframes and signal rules are unchanged. Order-flow ranking
weight remains at its existing value and the hard veto remains disabled.

The supplied V6 values retain 1h trend, 30m confirmation, 15m entry, and 5m/15m
live recovery confirmation. They do not copy V7's strategy timeframes.

## One-time local/VPS deployment

`data/open_trades_v6.json` is now runtime-only and ignored by Git. A first pull
that contains its repository deletion can remove the previously tracked copy.

1. Stop v6 and verify no local or VPS v6 process is still trading the account.
2. Copy `data/open_trades_v6.json` and `.env` outside the checkout. Validate the
   state backup as JSON and retain its checksum.
3. Deploy/pull the code.
4. Restore the state file to the configured `DCA_STATE_PATH`, with write access
   for the service user. On VPS, an absolute path outside the checkout is safer
   for future deployments.
5. Merge [v6_upgrade.env.example](v6_upgrade.env.example) into the existing
   `.env`; do not replace API keys, symbols, or strategy settings.
6. Confirm the Binance account is in one-way mode, then start exactly one v6
   instance. Never run local and VPS instances against the same account together.
7. Inspect the first reconciliation cycle, protection-order IDs, and both
   telemetry files before allowing unattended operation.

Positions opened before this upgrade are intentionally not auto-migrated into
the fixed-risk campaign. With `DCA_MANAGE_EXISTING_POSITIONS=False`,
`POSITION_MANAGEMENT_LEGACY_ENABLED=False`, and
`HARD_STOP_RECONCILE_LEGACY_POSITIONS=False`, the bot will not invent a risk
budget or recovery add for a legacy position. Review any such position and its
exchange-side protection manually before deployment.

## Position-management flow with the supplied values

For a new trend trade, the bot calculates one hard-stop price before entry and
sizes the entire campaign to at most 0.5% of conservative account equity. Up to
70% of both the campaign margin and risk budget is available to the initial
entry; the remaining 30% is reserved for one recovery add. At -25% leveraged
ROI the recovery is only armed. It can fill only after at least an 8% leveraged
ROI rebound, supportive 5m and 15m checks, the existing V6 continuation guard,
the one-hour cooldown/price-gap rules, and exact exchange-stop verification.

A confirmed trend invalidation can close from 15 minutes onward while ROI is at
or below -20%. If no earlier owner closes the trade, a trend position that is at
least 240 minutes old and no better than 0% ROI can close only when the V6 30m
weakness score reaches 2, with the 1h frame providing additional evidence. A
recovery fill adds a 30-minute time-exit grace period. The immutable hard stop
remains the final price-based loss boundary throughout.

## Offline verification

```powershell
venv\Scripts\python.exe -m unittest discover -s tests
venv\Scripts\python.exe -m py_compile config.py exchange.py execution_telemetry.py main.py market_intelligence.py multi_tp.py order_flow_shadow.py trade_state.py
```

Offline tests and static review do not replace a controlled testnet or minimal-size
exchange smoke test after VPS deployment.
