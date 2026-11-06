"""Forecast journal: a TradingAgents-style team that writes down market views every trading day
and a hypothetical book that scores them. FORWARD TEST ONLY; it never places an order.

    uv run python -m horizon_trader.agents.journal run      # 15:00 ET: mark, analyse, decide
    uv run python -m horizon_trader.agents.journal score    # mark/close positions, rescore only
    uv run python -m horizon_trader.agents.journal report   # print the scorecard

Pipeline (research/forecast_journal/README.md):
  market packet (code) -> analysts: market (packet only), news + earnings (web search)
  -> bull and bear cases -> rebuttals -> trader (JSON schema) -> risk check and pricing (code)
  -> book + mirrors -> scoring.
Each role is one headless `claude -p` call (your Claude login, no API key), run from a temp
directory so the repo's CLAUDE.md and research evidence don't leak into the prompt. Only the
news and earnings analysts get tools (WebSearch, WebFetch). Every prompt, raw answer, model ID
and prompt hash is saved under data/journal/days/<date>/ before any outcome exists, and a day is
never rebuilt.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from horizon_trader import config
from horizon_trader.agents import book, prompts
from horizon_trader.agents.market import Market, packet

NY = ZoneInfo("America/New_York")
MODELS = {"analyst": "claude-sonnet-5-5", "debate": "claude-opus-5-5", "trader": "claude-opus-5-5"}
WEB = ["WebSearch", "WebFetch"]
LEDGER = "journal_shadow"  # data/live/journal_shadow -> the dashboard's Live page

# runner(prompt, model, tools, schema) -> the `claude -p --output-format json` wrapper dict
Runner = Callable[[str, str, list[str], dict | None], dict]


def root() -> Path:
    return config.data_dir() / "journal"


def claude_cmd(model: str, tools: list[str], schema: dict | None) -> list[str]:
    cmd = ["claude", "-p", "--model", model, "--output-format", "json", "--strict-mcp-config",
           "--no-session-persistence", "--tools", ",".join(tools)]  # fmt: skip
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]
    if schema is not None:
        cmd += ["--json-schema", json.dumps(schema)]
    return cmd


def claude(prompt: str, model: str, tools: list[str], schema: dict | None) -> dict:
    proc = subprocess.run(
        claude_cmd(model, tools, schema), input=prompt, capture_output=True, text=True,
        encoding="utf-8", timeout=1800, check=False, cwd=tempfile.gettempdir(),
    )  # fmt: skip
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p exit {proc.returncode}: {proc.stderr[:300]}")
    wrapper = json.loads(proc.stdout)
    if wrapper.get("is_error"):
        raise RuntimeError(f"claude -p failed: {str(wrapper.get('result'))[:300]}")
    return wrapper


def answer(wrapper: dict, structured: bool):
    if structured:
        return wrapper.get("structured_output") or json.loads(wrapper["result"])
    return str(wrapper.get("result", "")).strip()


def _section(title: str, body: str) -> str:
    return f"\n\n---\n\n## {title}\n\n{body.strip()}\n"


def positions_text(positions: list[dict]) -> str:
    rows = [p for p in positions if p["status"] == "open" and p["kind"] == "idea"]
    if not rows:
        return "(none)"
    out = []
    for p in rows:
        legs = " / ".join(
            f"{'+' if leg['side'] > 0 else '-'}{leg.get('symbol')}" for leg in p["legs"]
        )
        last = p.get("last_value")
        now = f"${last:,.0f}" if last is not None else "?"
        out.append(
            f"- {p['id']}: {p['structure']} {p['underlying']} ({legs}), opened {p['date']} for "
            f"${p['entry_cost']:,.0f}, now {now}"
            f", closes by {p['exit_planned']}. Thesis: {p['thesis']} Invalidation: "
            f"{p['invalidation']}"
        )
    return "\n".join(out)


class Day:
    """One trading day's folder: inputs, every role's prompt and raw answer, the decision."""

    def __init__(self, today: str):
        self.today = today
        self.dir = root() / "days" / today
        (self.dir / "reports").mkdir(parents=True, exist_ok=True)
        (self.dir / "raw").mkdir(exist_ok=True)

    def report(self, role: str) -> str | None:
        p = self.dir / "reports" / f"{role}.md"
        return p.read_text(encoding="utf-8") if p.exists() else None

    def call(self, role: str, prompt: str, model: str, tools: list[str], runner: Runner,
             schema: dict | None = None):  # fmt: skip
        """Run one role once; a finished role is read back instead of re-asked."""
        if schema is None and (done := self.report(role)) is not None:
            return done
        (self.dir / "raw" / f"{role}.prompt.md").write_text(prompt, encoding="utf-8")
        started = datetime.now(NY).isoformat(timespec="seconds")
        wrapper = runner(prompt, model, tools, schema)
        finished = datetime.now(NY).isoformat(timespec="seconds")
        rec = {"role": role, "model": model, "tools": tools, "started": started,
               "finished": finished, "wrapper": wrapper}  # fmt: skip
        (self.dir / "raw" / f"{role}.json").write_text(json.dumps(rec, indent=1), "utf-8")
        out = answer(wrapper, schema is not None)
        if schema is None:
            (self.dir / "reports" / f"{role}.md").write_text(out + "\n", encoding="utf-8")
        return out


def validate(decision: dict) -> list[str]:
    problems = []
    have = {(f["ticker"].upper(), f["horizon_days"]) for f in decision["forecasts"]
            if not f.get("benchmark")}  # fmt: skip
    for t, h in prompts.MANDATORY:
        if (t, h) not in have:
            problems.append(f"missing mandatory forecast {t} {h}d")
    if len(decision["forecasts"]) > len(prompts.MANDATORY) + 4:
        problems.append("more than 4 optional forecasts; extras ignored")
    return problems


def forecast_rows(decision: dict, today: str, model: str) -> list[dict]:
    rows, optional = [], 0
    for f in decision["forecasts"]:
        t = f["ticker"].upper().strip()
        mandatory = (t, f["horizon_days"]) in prompts.MANDATORY and not f.get("benchmark")
        if not mandatory:
            optional += 1
            if optional > 4:
                continue
        rows.append({"date": today, "ticker": t, "horizon_days": f["horizon_days"],
                     "direction": f["direction"], "benchmark": f.get("benchmark") or "",
                     "confidence": f["confidence"], "mandatory": mandatory,
                     "prompt_sha": prompts.prompt_sha(), "model": model})  # fmt: skip
    return rows


def append_forecasts(rows: list[dict]) -> None:
    path = root() / "forecasts.csv"
    new = pd.DataFrame(rows)
    if path.exists():
        old = pd.read_csv(path, dtype={"date": str, "benchmark": str}, keep_default_na=False)
        new = pd.concat([old, new]).drop_duplicates(
            ["date", "ticker", "horizon_days", "benchmark"], keep="first"
        )
    new.to_csv(path, index=False)


def run(today: str, market: Market, runner: Runner = claude, models: dict | None = None,
        rules: book.Rules | None = None) -> dict:  # fmt: skip
    models = MODELS | (models or {})
    rules = rules or book.Rules()
    day = Day(today)
    if (day.dir / "decision.json").exists():
        raise SystemExit(f"{today} already has a decision; days are never rebuilt")
    now = datetime.now(NY).strftime("%H:%M")
    head = prompts.COMMON.format(today=today, now=now)

    positions = book.load(root())
    marks = mark_book(positions, market, today, rules)

    if (day.dir / "packet.md").exists():
        pkt = (day.dir / "packet.md").read_text(encoding="utf-8")
    else:
        pkt, nums = packet(market, today)
        (day.dir / "packet.md").write_text(pkt, encoding="utf-8")
        (day.dir / "packet.json").write_text(json.dumps(nums, indent=1, default=float), "utf-8")

    web = prompts.WEB_RULES.format(now=now)
    jobs = {
        "market": (head + prompts.ANALYSTS["market"] + _section("Market packet", pkt), []),
        "news": (head + prompts.ANALYSTS["news"] + web + _section("Market packet", pkt), WEB),
        "earnings": (head + prompts.ANALYSTS["earnings"] + web + _section("Market packet", pkt),
                     WEB),
    }  # fmt: skip
    with ThreadPoolExecutor(3) as ex:
        futures = {r: ex.submit(day.call, r, p, models["analyst"], t, runner)
                   for r, (p, t) in jobs.items()}  # fmt: skip
        reports = {r: f.result() for r, f in futures.items()}
    evidence = _section("Market packet", pkt) + "".join(
        _section(f"{r.title()} analyst", reports[r]) for r in jobs
    )

    with ThreadPoolExecutor(2) as ex:
        cases = {
            side: ex.submit(day.call, side, head + prompts.DEBATE[side] + evidence,
                            models["debate"], [], runner)
            for side in ("bull", "bear")
        }  # fmt: skip
        cases = {k: v.result() for k, v in cases.items()}
    debate_text = _section("Bull case", cases["bull"]) + _section("Bear case", cases["bear"])
    with ThreadPoolExecutor(2) as ex:
        rebut = {
            side: ex.submit(day.call, f"{side}_rebuttal",
                            head + prompts.DEBATE[f"{side}_rebuttal"] + debate_text,
                            models["debate"], [], runner)
            for side in ("bull", "bear")
        }  # fmt: skip
        rebut = {k: v.result() for k, v in rebut.items()}
    debate_text += _section("Bull rebuttal", rebut["bull"]) + _section(
        "Bear rebuttal", rebut["bear"]
    )

    trader_prompt = head + prompts.TRADER.format(
        max_new=rules.max_new, account=rules.account, premium_cap=rules.premium_cap,
        premium_total=rules.premium_total, shares_cap=rules.shares_cap,
        max_open=rules.max_open, positions=positions_text(positions),
    ) + evidence + debate_text  # fmt: skip
    decision = day.call("trader", trader_prompt, models["trader"], [], runner, prompts.SCHEMA)

    # ---- code takes over: close, price, risk-check, record ----
    close_ids = set(decision.get("close_ids") or [])
    marks += book.step(positions, market, today, rules, close_ids)
    resolution = book.open_ideas_with_mirrors(decision["ideas"], market, today, rules, positions)
    append_forecasts(forecast_rows(decision, today, models["trader"]))
    record = {
        "date": today, "decided_at": datetime.now(NY).isoformat(timespec="seconds"),
        "prompt_sha": prompts.prompt_sha(), "models": models, "rules": book.rules_dict(rules),
        "decision": decision, "problems": validate(decision), "resolution": resolution,
        "closed_by_trader": sorted(close_ids),
    }  # fmt: skip
    (day.dir / "decision.json").write_text(json.dumps(record, indent=1, default=float), "utf-8")
    book.save(root(), positions, marks)
    rescore(market, positions)
    return record


def mark_book(positions: list[dict], market: Market, today: str, rules: book.Rules) -> list:
    marks = book.step(positions, market, today, rules)
    last = {m["id"]: m["value"] for m in marks}
    for p in positions:
        if p["id"] in last:
            p["last_value"] = last[p["id"]]
    return marks


def write_ledger(positions: list[dict], rules: book.Rules) -> None:
    path = root() / "marks.csv"
    marks = pd.read_csv(path, dtype={"date": str, "id": str}) if path.exists() else pd.DataFrame()
    eq = book.equity_curve(positions, marks, rules)
    if eq.empty:
        return
    out = config.data_dir() / "live" / LEDGER
    out.mkdir(parents=True, exist_ok=True)
    eq.to_csv(out / "equity.csv", index=False)
    held = {
        (leg["symbol"] if p["legs"][0]["type"] == "option" else p["underlying"]):
            leg["side"] * p["qty"]
        for p in book.open_ideas(positions) for leg in p["legs"]
    }  # fmt: skip
    state = {"cash": float(eq["cash"].iloc[-1]), "holdings": held, "pending": [],
             "note": "Hypothetical forecast-journal book; see data/journal/book.json"}  # fmt: skip
    (out / "state.json").write_text(json.dumps(state, indent=1), encoding="utf-8")


def rescore(market: Market, positions: list[dict] | None = None) -> dict:
    """Score every forecast with today's closes and write the files the dashboard reads."""
    positions = book.load(root()) if positions is None else positions
    rules = book.Rules()
    write_ledger(positions, rules)
    path = root() / "forecasts.csv"
    fc = (
        pd.read_csv(path, dtype={"date": str, "benchmark": str}, keep_default_na=False)
        if path.exists()
        else pd.DataFrame(columns=["date", "ticker", "horizon_days", "direction", "benchmark",
                                   "confidence", "mandatory"])
    )  # fmt: skip
    if len(fc):
        fc["mandatory"] = fc["mandatory"].astype(str).str.lower() == "true"
        start = (pd.Timestamp(fc["date"].min()) - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        closes = market.closes(sorted(set(fc["ticker"]) | {"SPY"}), start)
        scored = book.score_forecasts(fc, closes)
    else:
        scored = fc.assign(exit_date=None, ret=None, bench_ret=None, edge=None, hit=None)
    scored.to_csv(root() / "scored_forecasts.csv", index=False)
    summ = book.summary(scored, positions) | {
        "updated": datetime.now(NY).isoformat(timespec="seconds")
    }
    (root() / "summary.json").write_text(json.dumps(summ, indent=1, default=float), "utf-8")
    return summ


def score(today: str, market: Market) -> dict:
    """Mark and close positions without a new decision (for days the full run is skipped)."""
    rules = book.Rules()
    positions = book.load(root())
    marks = mark_book(positions, market, today, rules)
    book.save(root(), positions, marks)
    return rescore(market, positions)


def report() -> None:
    path = root() / "summary.json"
    if not path.exists():
        print("no journal yet: run `python -m horizon_trader.agents.journal run`")
        return
    s = json.loads(path.read_text(encoding="utf-8"))
    print(f"Forecast journal, updated {s['updated']}")
    for f in s["forecasts"]:
        if not f["n"]:
            continue
        print(f"  {f['horizon']:>2}d {f['group']:<20} n={f['n']:<4} hit {f['hit_rate']:.0%} "
              f"(always-up {f['always_up_hit_rate']:.0%}) edge {f['mean_edge_pct']:+.2f}% "
              f"t={f['t_nonoverlap'] if f['t_nonoverlap'] is None else round(f['t_nonoverlap'], 2)}"
              f" (n={f['n_nonoverlap']} non-overlapping)")  # fmt: skip
    i = s["ideas"]
    print(f"  ideas: {i['opened']} opened, {i['closed']} closed, P&L ${i['pnl']:,.0f}; "
          f"paired with mirrors: ideas ${i['pnl_paired']:,.0f} vs mirrors "
          f"${i['mirror_pnl_paired']:,.0f} (n={i['paired']})")  # fmt: skip


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("command", choices=["run", "score", "report"])
    p.add_argument("--date", default=datetime.now(NY).strftime("%Y-%m-%d"))
    p.add_argument("--analyst-model", default=MODELS["analyst"])
    p.add_argument("--model", default=MODELS["trader"], help="debate and trader model")
    p.add_argument(
        "--no-ibkr",
        action="store_true",
        help="Yahoo's delayed option quotes only (default: live IBKR quotes first)",
    )
    a = p.parse_args()
    if a.command == "report":
        report()
        return
    config.require_ops(f"journal {a.command}")
    from horizon_trader.agents.market import YahooMarket, is_weekday

    if not is_weekday(a.date):
        raise SystemExit(f"{a.date} is a weekend")
    if a.command == "run" and a.date != datetime.now(NY).strftime("%Y-%m-%d"):
        raise SystemExit("run only accepts today's New York date: past days are never back-filled")
    from horizon_trader.datasources.ibkr_quotes import IBKRQuotes

    market = YahooMarket(quotes=None if a.no_ibkr else IBKRQuotes(client_id=31))
    if a.command == "score":
        score(a.date, market)
    else:
        now = datetime.now(NY)
        if not (9 * 60 + 45 <= now.hour * 60 + now.minute <= 16 * 60):
            print("warning: outside 9:45-16:00 ET; option quotes are stale, ideas will be rejected")
        models = {"analyst": a.analyst_model, "debate": a.model, "trader": a.model}
        rec = run(a.date, market, models=models)
        d = rec["decision"]
        print(f"{a.date}: {d['regime']}, {d['bias']} (debate: {d['debate_winner']})")
        for r in rec["resolution"]:
            print(f"  idea {r['n'] + 1}: {r['idea']['structure']} {r['idea']['underlying']} -> "
                  f"{r['status']} ({r['reason']})")  # fmt: skip
        for prob in rec["problems"]:
            print("  problem:", prob)
    report()


if __name__ == "__main__":
    main()
