"""Stance labels (bullish / bearish / neutral) for every Serenity cashtag mention.

    uv run python -m horizon_trader.social.stance export   # write the batches to label
    uv run python -m horizon_trader.social.stance check    # coverage and label counts

Labels are written by Claude reading each post (see GUIDE), one JSONL file per batch:
    <data_dir>/social/serenity/stance/batches/batch_NNN.json   input: posts + tickers to label
    <data_dir>/social/serenity/stance/labels/batch_NNN.jsonl   output: {"id", "ticker", "stance"}
A batch with a complete labels file is done, so labelling can stop and resume at any point.

Caveat: the labelling model's training data runs past many of these posts, so it may know what
happened next. The guide tells it to judge the text alone; spot-check a sample by hand.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from horizon_trader.social import archive

STANCES = ("bullish", "bearish", "neutral")
BATCH_SIZE = 120
QUOTE_CHARS = 600  # quoted posts are context only; keep them short

GUIDE = """Label the AUTHOR's stance on each listed ticker in each post, as of the moment he
posted, from the post text alone.

bullish  he owns / bought / is adding, says it will go up, is undervalued, a winner or
         beneficiary of the news, "long", raises a target, or calls it a top pick
bearish  he sold / trimmed / exited, is short, says it's overvalued, a loser from the news,
         the thesis is broken, or to avoid it
neutral  context, news without a view, a comparison or supply-chain mention without a view,
         a question, a joke, a list of tickers, someone else's opinion, or mixed / unclear

Rules:
- One label per (post, ticker); a post can be bullish on one ticker and neutral on others.
- Quoted text is someone else's post (often his own earlier one); use it only to understand
  what he is replying to. The stance must come from what he writes in THIS post.
- Judge the text only. Do not use anything you know about what happened after the post date
  (later prices, earnings, events). If you recognise the stock's later path, ignore it.
- When unsure between bullish and neutral, choose neutral. Sarcasm counts by its meaning."""


def root() -> Path:
    return archive.root() / "stance"


def export(batch_size: int = BATCH_SIZE) -> int:
    posts, ments = archive.load()
    tickers = ments.groupby("id")["ticker"].apply(list)
    todo = posts[posts["id"].isin(tickers.index)].sort_values("ts")
    out = root() / "batches"
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for n, start in enumerate(range(0, len(todo), batch_size)):
        chunk = todo.iloc[start : start + batch_size]
        items = [
            {
                "id": p.id,
                "posted": f"{p.ts:%Y-%m-%d %H:%M} ET",
                "text": p.text,
                "quoted": p.quoted_text[:QUOTE_CHARS],
                "tickers": tickers[p.id],
            }
            for p in chunk.itertuples()
        ]
        path = out / f"batch_{n:03d}.json"
        path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    (root() / "GUIDE.txt").write_text(GUIDE, encoding="utf-8")
    return n + 1


def _expected(batch: Path) -> set[tuple[str, str]]:
    items = json.loads(batch.read_text(encoding="utf-8"))
    return {(i["id"], t) for i in items for t in i["tickers"]}


def read_labels(path: Path) -> pd.DataFrame:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return pd.DataFrame(rows, columns=["id", "ticker", "stance"]).astype(str)


def check() -> pd.DataFrame:
    """Per batch: mentions expected, labelled, missing, invalid, extra."""
    rows = []
    for batch in sorted((root() / "batches").glob("batch_*.json")):
        want = _expected(batch)
        path = root() / "labels" / f"{batch.stem}.jsonl"
        got = read_labels(path) if path.exists() else pd.DataFrame(columns=["id", "ticker"])
        keys = set(zip(got["id"], got["ticker"], strict=True))
        bad = int((~got.get("stance", pd.Series(dtype=str)).isin(STANCES)).sum())
        rows.append(
            {
                "batch": batch.stem,
                "expected": len(want),
                "labelled": len(keys & want),
                "missing": len(want - keys),
                "invalid": bad,
                "extra": len(keys - want),
            }
        )
    return pd.DataFrame(rows).set_index("batch")


def load() -> pd.DataFrame:
    """Every label: id, ticker, stance (last line wins if a pair was written twice)."""
    files = sorted((root() / "labels").glob("batch_*.jsonl"))
    if not files:
        raise FileNotFoundError("no stance labels yet: run `stance export` and label the batches")
    df = pd.concat([read_labels(f) for f in files], ignore_index=True)
    df = df[df["stance"].isin(STANCES)].drop_duplicates(["id", "ticker"], keep="last")
    return df.reset_index(drop=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("cmd", choices=["export", "check"])
    args = p.parse_args()
    if args.cmd == "export":
        print(f"wrote {export()} batches to {root() / 'batches'}")
        return
    c = check()
    print(c.to_string())
    print(
        f"\ndone: {(c['missing'] == 0).sum()}/{len(c)} batches, "
        f"{c['labelled'].sum():,}/{c['expected'].sum():,} mentions"
    )
    if c["labelled"].sum():
        print(load()["stance"].value_counts().to_string())


if __name__ == "__main__":
    main()
