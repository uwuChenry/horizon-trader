# Alpha formulas on ~100 large caps, 2010-2023

**Verdict: nothing significant.** None of the 20 formula variants reached t > 2 in its claimed
direction. The formula libraries in this folder (`classics.yaml`, `kou2025_table3.yaml`) are
inputs to `horizon_trader.alphas.cli`; each formula's direction was recorded before testing.

- 12-month momentum and 1-week reversal each came in at t ~ 1.95.
- The Kou et al. ([arXiv 2409.06289](https://arxiv.org/abs/2409.06289)) formulas are mostly
  noise; their 14-day momentum predicts the wrong way.
- Low volatility has the wrong sign, which is survivorship bias at work: the universe
  (`config/universes/us_large_cap.yaml`) is today's large caps.
- Top-3 momentum shows 33% CAGR, but its Sharpe equals equal weight's, so the extra return is
  survivors plus concentration.
- Weekly reversal is destroyed by commissions ($11k on a $5k account).

Rank IC is computed by `uv run python -m horizon_trader.alphas.cli evaluate <yaml...>`; 2024
onward is a holdout, hidden unless `--holdout` is passed. Paper-to-formula extraction
(`alphas.cli extract`) is built but has never run against the real API.
