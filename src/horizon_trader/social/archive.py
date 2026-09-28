"""The @aleabitoreddit ("Serenity") post archive: download, parse, extract $cashtag mentions.

    uv run python -m horizon_trader.social.archive [--ref <commit>]

Source: github.com/yan-labs/serenity-aleabitoreddit, a fan-maintained scrape of his public X
posts (6,592 posts, 2025-07-02 .. 2026-09-17 at the pinned commit). The account itself was
created 2025-07-02 (its user id is a snowflake), so the archive starts at the first post and a
"first mention" in it really is his first mention on this account.

Timestamps come from the post id, not the scraped date: X ids are snowflakes whose top bits
are milliseconds since 2010-11-04, set by X when the post was created and impossible to
backdate. The scraped `createdAtISO` is checked against it.

Known gaps, reported by the study rather than fixed:
- Deleted posts are missing. Deleted calls are more likely to be bad ones, so the archive
  can only flatter him.
- Long posts ("Note Tweets") may be truncated to an excerpt, dropping cashtags past the cut.
- A cashtag is a mention, not a recommendation: stance (long / short / neutral) isn't
  extracted yet, so every mention is treated as a long call.

Saved under <data_dir>/social/serenity/: raw JSON (as downloaded), posts.parquet,
mentions.parquet and source.json (commit, download time).
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from horizon_trader.config import data_dir

REPO = "yan-labs/serenity-aleabitoreddit"
PINNED_REF = "20e9e907b6ee17c843da9a498dcad6bfb7322efc"  # 2026-09-18, last post 2026-09-17
ARCHIVE_PATH = "data/aleabitoreddit_tweets.json"
TZ = "America/New_York"
TWITTER_EPOCH_MS = 1288834974657
# $NVDA, $BRK.B; not $150k (digits) and not the $ of a price. The lookbehind skips "US$".
CASHTAG = re.compile(r"(?<![A-Za-z0-9$])\$([A-Za-z]{1,5}(?:\.[A-Za-z]{1,2})?)(?![A-Za-z0-9])")


def root() -> Path:
    return data_dir() / "social" / "serenity"


def snowflake_time(post_id: str | int) -> pd.Timestamp:
    """Creation time encoded in an X id (UTC, millisecond precision)."""
    ms = (int(post_id) >> 22) + TWITTER_EPOCH_MS
    return pd.Timestamp(ms, unit="ms", tz="UTC")


def cashtags(text: str) -> list[str]:
    """Distinct $TICKERS in order of first appearance, upper-cased."""
    seen: dict[str, None] = {}
    for m in CASHTAG.finditer(text or ""):
        seen.setdefault(m.group(1).upper(), None)
    return list(seen)


def download(ref: str = PINNED_REF) -> Path:
    url = f"https://raw.githubusercontent.com/{REPO}/{ref}/{ARCHIVE_PATH}"
    out = root() / f"tweets_{ref[:12]}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists() or not re.fullmatch(r"[0-9a-f]{40}", ref):  # branches move
        with urllib.request.urlopen(url, timeout=120) as resp:
            out.write_bytes(resp.read())
    source = {"repo": REPO, "ref": ref, "url": url, "downloaded": datetime.now(UTC).isoformat()}
    (root() / "source.json").write_text(json.dumps(source, indent=2), encoding="utf-8")
    return out


def parse_posts(raw: list[dict]) -> pd.DataFrame:
    """One row per post: id, ts (New York time, from the id), text, retweet flag, engagement."""
    rows = []
    for p in raw:
        m = p.get("metrics") or {}
        rows.append(
            {
                "id": str(p["id"]),
                "ts": snowflake_time(p["id"]).tz_convert(TZ),
                "scraped_ts": pd.Timestamp(p["createdAtISO"]) if p.get("createdAtISO") else None,
                "text": p.get("text") or "",
                "is_retweet": bool(p.get("isRetweet", False)),
                "quoted_text": (p.get("quotedTweet") or {}).get("text") or "",
                "likes": m.get("likes"),
                "views": m.get("views"),
            }
        )
    df = pd.DataFrame(rows).drop_duplicates("id")
    return df.sort_values("ts", ignore_index=True)


def mentions(posts: pd.DataFrame) -> pd.DataFrame:
    """One row per (post, ticker) for tickers he cashtags in his OWN text. Retweets and the
    text of quoted posts don't count: those are someone else's calls."""
    own = posts[~posts["is_retweet"]]
    rows = [
        {"id": p.id, "ts": p.ts, "ticker": t, "n_tickers": len(tags)}
        for p in own.itertuples()
        for tags in [cashtags(p.text)]
        for t in tags
    ]
    df = pd.DataFrame(rows, columns=["id", "ts", "ticker", "n_tickers"])
    first = df.groupby("ticker")["ts"].transform("min")
    return df.assign(first_mention=df["ts"] == first)


def build(ref: str = PINNED_REF) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = json.loads(download(ref).read_text(encoding="utf-8"))
    posts = parse_posts(raw)
    ments = mentions(posts)
    posts.to_parquet(root() / "posts.parquet", index=False)
    ments.to_parquet(root() / "mentions.parquet", index=False)
    return posts, ments


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not (root() / "mentions.parquet").exists():
        return build()
    return pd.read_parquet(root() / "posts.parquet"), pd.read_parquet(root() / "mentions.parquet")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--ref", default=PINNED_REF, help="archive commit (default: pinned)")
    args = p.parse_args()
    posts, ments = build(args.ref)
    skew = (posts["ts"] - posts["scraped_ts"].dt.tz_convert(TZ)).abs().dt.total_seconds()
    print(f"posts: {len(posts):,} ({posts['is_retweet'].sum():,} retweets), "
          f"{posts['ts'].min():%Y-%m-%d} .. {posts['ts'].max():%Y-%m-%d}")  # fmt: skip
    print(f"scraped time vs id time: max difference {skew.max():.0f}s")
    print(f"mentions: {len(ments):,} of {ments['ticker'].nunique():,} tickers")
    per_day = posts.set_index("ts").resample("D").size()
    print(f"posts per day: median {per_day.median():.0f}, days with none: {(per_day == 0).sum()}")


if __name__ == "__main__":
    main()
