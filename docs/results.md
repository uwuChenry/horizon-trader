# Results and dashboard

Run `uv run python -m horizon_trader.dashboard` (build the frontend first with
`cd web && npm install && npm run build`). The **Research** page lists every study under
`research/` by status, with its report, documents and data files. **Backtests** lists every
bundle under `data/results`; **Live** shows the ledgers under `data/live` and the IBKR
observation logs. Pages read files on each request: refreshing never fetches market data or
reruns a strategy.

## Common contract

`src/horizon_trader/results/catalog.py` is the shared discovery and reader layer.
Every result has a stable ID, name, kind, optional data dates, description and typed
artifacts. It distinguishes reports, metrics, equity, trades, verification and metadata.
Recorded source values, metric definitions, costs and periods are preserved. Order
fills and gross trade paths are not converted into invented round-trip statistics.

Old `data/results/<run>/meta.json` bundles are adapted directly, without migration
or duplication. `bundle.save_run()` now also writes a version 1 `result.json`.
Research uses the same descriptor: every folder under `research/` has one, next to its
README; large CSV/Parquet evidence stays under `data/` and is referenced as `data:...`.

To register a new study, write artifacts first, then publish this descriptor in
`research/<study>/result.json` (or `data/results/<run>/result.json`). Research studies also
carry the curated fields `status`, `verdict` and `tags` (see `results/index.py`); re-running a
script with `write_manifest` keeps them. Then regenerate `research/README.md` with
`uv run python -m horizon_trader.results.index`:

```json
{
  "schema_version": 1,
  "id": "research:my-study",
  "name": "My study",
  "kind": "research",
  "description": "Scope, assumptions and limitations of this experiment.",
  "start": "2020-01-01",
  "end": "2026-10-01",
  "include": ["*.md", "results/*.csv", "results/*.json"],
  "artifacts": [
    {"path": "data:my-study/equity.parquet", "role": "equity", "label": "All configurations"}
  ]
}
```

`include` uses relative globs; `artifacts` provides explicit labels/roles and retains
missing-file entries so the UI can explain unavailable local data. `data:` paths
resolve against `HT_DATA_DIR`, not a hard-coded machine path. Other paths are relative
to the descriptor. References must remain inside their selected root. Use
`results.catalog.write_manifest(path, **fields)` to write the descriptor atomically.
No dashboard edits or manual copies are needed for a new registered study.

Equity readers support a datetime index, a wide `date, strategy_a, strategy_b` table,
or a long `date, equity, strategy, capital, ...` table. Supported configuration
dimensions are documented in `equity_curves()`. Duplicate date/configuration rows
are rejected rather than averaged. Each account/configuration remains a separate curve.
Metric tables retain their original column names so different Sharpe/cost conventions
are not accidentally treated as equivalent.

Forward equity/fill/state files under `data/live/<ledger>` and JSONL files under
`data/live/observations` are discovered automatically. Shadow ledgers are labeled
separately; observation logs include connection failures as well as successes.
File modification times are shown separately from the dates covered by the data.

## Save software test evidence

```powershell
.venv\Scripts\python.exe -m horizon_trader.results.check
# Or a focused run; the exact selection is recorded:
.venv\Scripts\python.exe -m horizon_trader.results.check tests/test_bundle.py -q -p no:cacheprovider
```

This runs pytest and writes its actual exit status, counts, JUnit XML, captured output,
timestamps and code/config fingerprint to `data/checks/<timestamp>/`. Failures and
collection errors remain visible. Historical research verification JSON remains historical evidence;
viewing it does not rerun or certify the underlying experiment.

Data and check outputs remain git-ignored. Descriptors and reports in `research/`
are tracked; collaborators without the local Parquet data can still read the reports
and tracked CSVs, and explicit missing artifacts are identified in the viewer.
