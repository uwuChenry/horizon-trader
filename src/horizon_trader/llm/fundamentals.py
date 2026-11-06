"""Monthly LLM fundamental scores for the 200 largest US companies: a FORWARD test.

    uv run python -m horizon_trader.llm.fundamentals export [--asof YYYY-MM-DD]  # build batches
    uv run python -m horizon_trader.llm.fundamentals run [--model M] [--workers 4]  # codex/claude
    uv run python -m horizon_trader.llm.fundamentals check [--model M]           # validate + log
    uv run python -m horizon_trader.llm.fundamentals evaluate                    # IC, top 20

`--asof` defaults to today. Batches can be scored two ways, and both write the same files:
`run` calls a headless CLI with every tool off and no API key: `codex exec` for GPT models
(the default from 2026-11-05, GPT-6.1 Sol, your ChatGPT login; llm/codex.py) or `claude -p` for
Claude models (your Claude login). Claude Code subagents can also read batches/batch_NN.md and
write scores/batch_NN.json themselves (the claude-opus-5-5 layout).
Everything lives under <data_dir>/llm/fundamental_scores/<asof>/: the inputs once per month,
then one score folder per model (scores/ for claude-opus-5-5, which scored 2026-10-01 and
2026-11-05; scores/<model>/ for any other) and scores[_<model>].parquet. A finished month is
never overwritten (`export` refuses) and a model can only START scoring a month on its as-of
date, so the log is append-only and nothing is back-filled.

What Claude sees per company (all filed BEFORE the as-of date, nothing later):
  - the last 8 fiscal quarters from SEC XBRL, as first reported: revenue, revenue growth vs a
    year earlier, gross and operating margins, operating and net income
  - the latest balance sheet (cash, long-term debt, assets, equity)
  - the latest earnings press release (8-K item 2.02) if newer than the last 10-Q/10-K
  - the start of the MD&A section of the latest 10-Q/10-K
No prices, market caps or valuation multiples (following Lehner & Lopez-Lira 2026): the score
is about the business, not whether the stock is cheap.

Pre-registered (2026-10-01, before any score existed; research/llm_fundamentals/README.md):
  signal     `score` (1-10); ties broken by the sum of the four sub-scores
  returns    from the close of the first trading day AFTER the as-of date; primary horizon
             21 trading days, secondary 63
  verdict    after at least 12 monthly runs:
             PASS if the mean 1-month rank IC is > 0 with t > 1 AND the top 20 by score beat
             the 200-name equal-weight universe on average monthly return
             KILL if the mean 1-month rank IC is <= 0
  rules      a different model is a new test (the model ID is logged with every score;
             `evaluate` reports each model separately);
             never back-fill past months (the model may know what happened next)
Power: a realistic IC of 0.02-0.05 needs years to prove; 12 months mainly rejects a bad signal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from horizon_trader.config import data_dir
from horizon_trader.llm.codex import codex, is_codex_model

UNIVERSE = 200
BATCH = 10
DEFAULT_MODEL = "gpt-6.1-sol"  # since 2026-11-05; claude-opus-5-5 scored 2026-10-01 and 11-05
LEGACY_MODEL = "claude-opus-5-5"  # its scores sit directly in scores/
MDNA_CHARS = 10_000
RELEASE_CHARS = 8_000
HORIZONS = {"1m": 21, "3m": 63}
TOP = 20
SUBSCORES = ["growth", "profitability", "balance_sheet", "outlook"]
DIRECTIONS = ["improving", "stable", "deteriorating"]

GUIDE = """# Fundamental scoring, forward test as of {asof}

You are scoring large US companies on their FUNDAMENTALS, from the filings below only.
- Use only the data in this file. Do not search the web, read other files or look up prices.
  General business knowledge is fine; stock prices, valuations and analyst targets are not.
- Score the business, not the stock: there are deliberately no prices or valuations here.
- Use an absolute scale that is comparable across batches: think of all ~200 of the largest
  US companies. About 10% deserve 8 or more, about 10% deserve 3 or less, 5 is a typical large
  cap. Don't grade on a curve within this batch.
- For banks and insurers, judge with what is given (they have no gross profit).

For EACH company return:
- `score` 1-10: overall strength and trajectory of the fundamentals over the next 12 months
  (1-2 deteriorating badly, 5 average, 9-10 exceptional and improving).
- `growth`, `profitability`, `balance_sheet`, `outlook` 1-10 each. `outlook` is the tone and
  guidance in the press release / MD&A.
- `direction`: "improving", "stable" or "deteriorating".
- `reason`: at most 40 words, citing the numbers that drove the score.

Output: JSON {{"scores": [{{"ticker", "score", "growth", "profitability", "balance_sheet",
"outlook", "direction", "reason"}}, ...]}} with one entry per company, tickers exactly as given.
"""

_INT = {"type": "integer", "minimum": 1, "maximum": 10}
SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "score": _INT,
                    **{k: _INT for k in SUBSCORES},
                    "direction": {"type": "string", "enum": DIRECTIONS},
                    "reason": {"type": "string"},
                },
                "required": ["ticker", "score", *SUBSCORES, "direction", "reason"],
            },
        }
    },
    "required": ["scores"],
}


def prompt_sha() -> str:
    return hashlib.sha256((GUIDE + json.dumps(SCHEMA, sort_keys=True)).encode()).hexdigest()[:12]


def run_dir(asof: str) -> Path:
    return data_dir() / "llm" / "fundamental_scores" / asof


# ---------- inputs ----------


def universe_asof(asof: str) -> tuple[pd.Timestamp, pd.DataFrame]:
    """The 200 largest US companies on the last trading day before `asof` (Massive
    point-in-time caps, one share class each): (that day, frame of ticker -> cik, name, cap)."""
    from horizon_trader.backtest import megacap as M
    from horizon_trader.datasources import massive, massive_ref
    from horizon_trader.intraday import features as F

    days = [d for d in massive.local_days("day") if d < date.fromisoformat(asof)]
    day = pd.Timestamp(days[-1])
    common = massive_ref.load_common_tickers()
    panels = F.load_daily_panels(days[-21:], common)
    dollar_vol = (panels["close"] * panels["volume"]).mean()
    cands = dollar_vol.nlargest(M.CANDIDATES).index
    caps = M.market_caps([(t, day.date()) for t in cands])
    top = M.top_n(caps, UNIVERSE)
    info = caps.drop_duplicates("ticker").set_index("ticker")
    return day, info.loc[top.index, ["cik", "name", "market_cap"]]


def _m(v: float) -> str:
    return "-" if pd.isna(v) else f"{v / 1e6:,.0f}"


def _pct(v: float) -> str:
    return "-" if pd.isna(v) else f"{v:+.1%}" if abs(v) < 100 else "n/m"


def company_payload(ticker: str, name: str, cik: str, asof: str) -> str:
    """Markdown block with everything Claude may see for one company."""
    from horizon_trader.datasources import sec

    facts = sec.company_facts(cik, max_age_days=1)
    subs = sec.submissions(cik, max_age_days=1)
    lines = [f"## {ticker}: {name}", ""]

    q = sec.quarterly_table(facts, asof)
    if q.empty:
        lines.append("No quarterly XBRL results available (e.g. a foreign filer).")
    else:
        lines += [
            "Quarterly results, USD millions, as first reported (Q4 = fiscal year minus Q1-Q3):",
            "",
            "| quarter end | filed | revenue | rev YoY | gross margin | op income | op margin "
            "| net income |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for end, r in q.iterrows():
            lines.append(
                f"| {end:%Y-%m-%d} | {r['filed']:%Y-%m-%d} | {_m(r['revenue'])} "
                f"| {_pct(r['revenue_yoy'])} | {_pct(r['gross_margin'])} "
                f"| {_m(r['operating_income'])} | {_pct(r['operating_margin'])} "
                f"| {_m(r['net_income'])} |"
            )
    bal = sec.latest_balance(facts, asof)
    if bal:
        parts = [f"{k.replace('_', ' ')} {_m(bal[k])}" for k in sec.BALANCE_TAGS if k in bal]
        lines += ["", f"Balance sheet as of {bal['as_of']} (USD millions): " + ", ".join(parts)]

    periodic = sec.filings(subs, ("10-Q", "10-K"), since="2025-01-01")
    periodic = periodic[periodic["filed"] < pd.Timestamp(asof)]
    last_filed = periodic["filed"].max() if len(periodic) else pd.Timestamp("1900-01-01")
    release = sec.earnings_release(subs, cik, asof)
    if release and pd.Timestamp(release["filed"]) > last_filed:
        text = release["text"][:RELEASE_CHARS]
        lines += ["", f"Latest earnings press release (8-K filed {release['filed']}), excerpt:"]
        lines += ["", "```", text, "```"]
    if len(periodic):
        f = periodic.iloc[-1]
        excerpt, found = sec.mdna_excerpt(sec.filing_text(cik, f["accn"], f["doc"]), MDNA_CHARS)
        what = "MD&A" if found else "opening text (MD&A heading not found)"
        lines += [
            "",
            f"{what} of the latest {f['form']} (period {f['period']}, filed "
            f"{f['filed']:%Y-%m-%d}), excerpt:",
            "",
            "```",
            excerpt,
            "```",
        ]
    return "\n".join(lines)


# ---------- export / run / check ----------


def export(asof: str, threads: int = 8) -> Path:
    out = run_dir(asof)
    if (out / "manifest.json").exists():
        raise SystemExit(f"{out} already exists: a scored month is never rebuilt")
    day, uni = universe_asof(asof)
    print(f"universe: {len(uni)} companies by market cap on {day.date()}")

    def build(t: str) -> tuple[str, str]:
        r = uni.loc[t]
        cik = str(r["cik"]) if pd.notna(r["cik"]) and str(r["cik"]).strip().isdigit() else None
        if cik is None:
            return t, f"## {t}: {r['name']}\n\nNo SEC filer ID; no filings available."
        return t, company_payload(t, r["name"], cik, asof)

    with ThreadPoolExecutor(threads) as ex:
        payloads = dict(ex.map(build, list(uni.index)))
    tickers = list(uni.index)
    random.Random(asof).shuffle(tickers)  # mix sectors across batches
    batches = {
        f"batch_{i // BATCH + 1:02d}": tickers[i : i + BATCH] for i in range(0, len(tickers), BATCH)
    }
    (out / "batches").mkdir(parents=True, exist_ok=True)
    (out / "scores").mkdir(exist_ok=True)
    for name, members in batches.items():
        body = GUIDE.format(asof=asof) + "\n\n" + "\n\n".join(payloads[t] for t in members)
        (out / "batches" / f"{name}.md").write_text(body, encoding="utf-8")
    manifest = {
        "asof": asof,
        "universe_date": str(day.date()),
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "prompt_sha": prompt_sha(),
        "batches": batches,
        "input_sha": {t: hashlib.sha256(p.encode()).hexdigest()[:12] for t, p in payloads.items()},
        "companies": {
            t: {"cik": None if pd.isna(r["cik"]) else str(r["cik"]), "name": r["name"],
                "market_cap": float(r["market_cap"])}
            for t, r in uni.iterrows()
        },
    }  # fmt: skip
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"wrote {len(batches)} batches to {out}")
    return out


def claude_cmd(model: str) -> list[str]:
    """Headless Claude Code with every tool and MCP server off: it can only read the prompt."""
    return [
        "claude", "-p", "--model", model, "--output-format", "json",
        "--json-schema", json.dumps(SCHEMA), "--tools", "", "--strict-mcp-config",
        "--no-session-persistence",
    ]  # fmt: skip


def parse_claude_output(stdout: str) -> list[dict]:
    """`claude -p --output-format json` wraps the answer; with --json-schema it's in
    `structured_output` (falling back to parsing `result`)."""
    wrapper = json.loads(stdout)
    if wrapper.get("is_error"):
        raise RuntimeError(f"claude -p failed: {wrapper.get('result')}")
    data = wrapper.get("structured_output") or json.loads(wrapper["result"])
    return data["scores"]


def scores_dir(out: Path, model: str) -> Path:
    return out / "scores" if model == LEGACY_MODEL else out / "scores" / model


def scores_parquet(out: Path, model: str) -> Path:
    return out / ("scores.parquet" if model == LEGACY_MODEL else f"scores_{model}.parquet")


def run(asof: str, model: str = DEFAULT_MODEL, workers: int = 4) -> None:
    out = run_dir(asof)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    sdir = scores_dir(out, model)
    started = sdir.exists() and any(sdir.glob("batch_*.json"))
    if not started and asof != date.today().isoformat():
        raise SystemExit(f"{model} has no scores for {asof}; a model only starts a month on its "
                         "as-of date (no back-fill)")  # fmt: skip
    sdir.mkdir(parents=True, exist_ok=True)
    todo = [b for b in manifest["batches"] if not (sdir / f"{b}.json").exists()]
    print(f"{len(todo)} of {len(manifest['batches'])} batches to score with {model}")

    def one(b: str) -> str:
        prompt = (out / "batches" / f"{b}.md").read_text(encoding="utf-8")
        if is_codex_model(model):
            try:
                wrapper = codex(prompt, model, web=False, schema=SCHEMA)
            except (RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
                return f"{b}: {str(e)[:200]}"
            write_scores(out, b, wrapper["structured_output"]["scores"], "codex exec", model,
                         extra={"reasoning_effort": wrapper["reasoning_effort"],
                                "usage": wrapper["usage"]})  # fmt: skip
            return f"{b}: ok"
        proc = subprocess.run(
            claude_cmd(model), input=prompt, capture_output=True, text=True, encoding="utf-8",
            timeout=1800, check=False,
        )  # fmt: skip
        if proc.returncode != 0:
            return f"{b}: exit {proc.returncode} {proc.stderr[:200]}"
        write_scores(out, b, parse_claude_output(proc.stdout), "claude -p", model)
        return f"{b}: ok"

    with ThreadPoolExecutor(workers) as ex:
        for msg in ex.map(one, todo):
            print(" ", msg, flush=True)


def write_scores(out: Path, batch: str, scores: list[dict], backend: str, model: str,
                 extra: dict | None = None) -> None:  # fmt: skip
    rec = {
        "backend": backend,
        "model": model,
        "scored_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **(extra or {}),
        "scores": scores,
    }
    sdir = scores_dir(out, model)
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / f"{batch}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")


def validate(manifest: dict, batch: str, rec: dict) -> list[str]:
    """Problems with one batch's scores (empty list = valid)."""
    want = set(manifest["batches"][batch])
    got = [s.get("ticker") for s in rec.get("scores", [])]
    errs = []
    if set(got) != want or len(got) != len(want):
        missing, extra = sorted(want - set(got)), sorted(set(got) - want)
        errs.append(f"tickers: missing {missing}, unexpected {extra}, {len(got)} entries")
    for s in rec.get("scores", []):
        for k in ["score", *SUBSCORES]:
            v = s.get(k)
            if not isinstance(v, int) or not 1 <= v <= 10:
                errs.append(f"{s.get('ticker')}: {k}={v!r}")
        if s.get("direction") not in DIRECTIONS:
            errs.append(f"{s.get('ticker')}: direction={s.get('direction')!r}")
    for k in ("backend", "model", "scored_at"):
        if not rec.get(k):
            errs.append(f"missing {k}")
    return errs


def company_blocks(batch_md: str) -> dict[str, str]:
    """{ticker: its section} from a batch file (sections start with "## TICKER: name")."""
    parts = batch_md.split("\n## ")[1:]
    return {part.split(":", 1)[0].strip(): part for part in parts}


def has_filings(block: str) -> bool:
    """False when Claude got no quarterly table and no filing text for the company (foreign
    20-F filers): its score then rests on general knowledge only, so it's left out of the
    evaluation (rule added 2026-10-01, before any return existed)."""
    return "| quarter end |" in block or "excerpt:" in block


def check(asof: str, model: str = DEFAULT_MODEL) -> pd.DataFrame | None:
    out = run_dir(asof)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    rows, problems = [], {}
    for b in manifest["batches"]:
        path = scores_dir(out, model) / f"{b}.json"
        if not path.exists():
            problems[b] = ["not scored yet"]
            continue
        rec = json.loads(path.read_text(encoding="utf-8"))
        blocks = company_blocks((out / "batches" / f"{b}.md").read_text(encoding="utf-8"))
        errs = validate(manifest, b, rec)
        if errs:
            problems[b] = errs
            continue
        for s in rec["scores"]:
            c = manifest["companies"][s["ticker"]]
            rows.append(
                {"asof": asof, "universe_date": manifest["universe_date"], **s,
                 "cik": c["cik"], "name": c["name"], "market_cap": c["market_cap"], "batch": b,
                 "backend": rec["backend"], "model": rec["model"], "scored_at": rec["scored_at"],
                 "prompt_sha": manifest["prompt_sha"],
                 "input_sha": manifest["input_sha"][s["ticker"]],
                 "has_filings": has_filings(blocks.get(s["ticker"], ""))}
            )  # fmt: skip
    done = len(manifest["batches"]) - len(problems)
    print(f"{asof} {model}: {done}/{len(manifest['batches'])} batches valid")
    for b, errs in problems.items():
        print(f"  {b}: {'; '.join(errs[:3])}")
    if problems:
        return None
    df = pd.DataFrame(rows)
    df.to_parquet(scores_parquet(out, model), index=False)
    no_data = df.loc[~df["has_filings"], "ticker"].tolist()
    print(f"no filings (excluded from evaluation): {', '.join(no_data) or 'none'}")
    print(df["score"].value_counts().sort_index().to_string())
    print("top 20:", ", ".join(ranked(df).head(TOP)["ticker"]))
    return df


def ranked(df: pd.DataFrame) -> pd.DataFrame:
    """Best first: score, then the sum of the sub-scores (pre-registered tie-break)."""
    key = df.assign(_sub=df[SUBSCORES].sum(axis=1))
    return key.sort_values(["score", "_sub"], ascending=False).drop(columns="_sub")


# ---------- evaluate ----------


def forward_returns(closes: pd.DataFrame, asof: str, horizon: int) -> pd.Series | None:
    """Close of the first trading day after asof -> `horizon` trading days later (None if the
    future hasn't happened yet)."""
    after = closes.index[closes.index > pd.Timestamp(asof)]
    if len(after) <= horizon:
        return None
    return closes.loc[after[horizon]] / closes.loc[after[0]] - 1


def evaluate_runs(runs: dict[str, pd.DataFrame], closes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for asof, df in sorted(runs.items()):
        if "has_filings" in df:
            df = df[df["has_filings"]]
        row = {"asof": asof, "model": df["model"].iloc[0], "n": len(df)}
        for label, h in HORIZONS.items():
            fwd = forward_returns(closes, asof, h)
            if fwd is None:
                row[f"IC {label}"] = row[f"top{TOP} {label}"] = row[f"universe {label}"] = np.nan
                continue
            r = df.set_index("ticker").assign(fwd=fwd).dropna(subset=["fwd"])
            r["rank_key"] = r["score"] + r[SUBSCORES].sum(axis=1) / 100
            row[f"IC {label}"] = r["rank_key"].rank().corr(r["fwd"].rank())
            top = ranked(r.reset_index()).head(TOP)["ticker"]
            row[f"top{TOP} {label}"] = r.loc[top, "fwd"].mean()
            row[f"universe {label}"] = r["fwd"].mean()
        rows.append(row)
    return pd.DataFrame(rows).set_index("asof")


def _closes(tickers: set[str], since: str) -> pd.DataFrame:
    from horizon_trader.datasources import massive, massive_ref
    from horizon_trader.intraday import features as F

    days = [d for d in massive.local_days("day") if d >= date.fromisoformat(since)]
    panels = F.load_daily_panels(days, tickers)
    factor = F.split_factors(
        panels["close"].index, panels["close"].columns, massive_ref.load_splits()
    )
    return panels["close"] * factor


def load_runs() -> dict[str, dict[str, pd.DataFrame]]:
    """{model: {asof: scores}} from every finished month (each model is its own test)."""
    base = data_dir() / "llm" / "fundamental_scores"
    out: dict[str, dict[str, pd.DataFrame]] = {}
    for p in sorted(base.glob("*/scores*.parquet")):
        df = pd.read_parquet(p)
        out.setdefault(str(df["model"].iloc[0]), {})[p.parent.name] = df
    return out


def evaluate() -> None:
    by_model = load_runs()
    if not by_model:
        print("no finished runs yet")
        return
    pd.set_option("display.width", 200)
    for model, runs in by_model.items():
        tickers = set().union(*[set(df["ticker"]) for df in runs.values()])
        table = evaluate_runs(runs, _closes(tickers, min(runs)))
        print(f"=== {model}")
        print(table.to_string(float_format=lambda v: f"{v:+.3f}"))
        ic = table["IC 1m"].dropna()
        print(f"{len(ic)} months with a 1-month result (verdict needs 12).", end=" ")
        if len(ic) > 2:
            t = ic.mean() / ic.std() * np.sqrt(len(ic))
            excess = (table[f"top{TOP} 1m"] - table["universe 1m"]).dropna().mean()
            print(f"Mean IC {ic.mean():+.3f} (t {t:+.2f}); top {TOP} minus universe "
                  f"{excess:+.2%}/month")  # fmt: skip
        else:
            print()
        print()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("command", choices=["export", "run", "check", "evaluate"])
    p.add_argument("--asof", default=date.today().isoformat())
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()
    if args.command == "export":
        export(args.asof)
    elif args.command == "run":
        run(args.asof, args.model, args.workers)
    elif args.command == "check":
        check(args.asof, args.model)
    else:
        evaluate()


if __name__ == "__main__":
    main()
