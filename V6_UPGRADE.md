# v6 execution, order-flow shadow, and TP runner upgrade

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
- Fail-closed one-way-mode and runtime-state validation, rolling state backup,
  graceful SIGINT/SIGTERM cleanup, and explicit execution-telemetry flushing.

The v6 strategy timeframes and signal rules are unchanged. Order-flow ranking
weight remains at its existing value and the hard veto remains disabled.

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

## Offline verification

```powershell
venv\Scripts\python.exe -m unittest discover -s tests
venv\Scripts\python.exe -m py_compile config.py exchange.py execution_telemetry.py main.py market_intelligence.py multi_tp.py order_flow_shadow.py trade_state.py
```

Offline tests and static review do not replace a controlled testnet or minimal-size
exchange smoke test after VPS deployment.
