"""Load DiscordChatExporter JSON exports into a flat message table.

Exports are made by hand with DiscordChatExporter (CLI, user token in .env as DISCORD_TOKEN)
into data/discord/raw/<channel id>_<YYYY-MM-DD>.json; this module only reads them. Using a
user token is against Discord's terms: export rarely, read-only.

Times come from the snowflake id (set by Discord when the message is sent, can't be
backdated); the export's own timestamp is the same instant and is checked against it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from horizon_trader.config import data_dir

TZ = "America/New_York"
DISCORD_EPOCH_MS = 1_420_070_400_000  # 2015-01-01 UTC


def root() -> Path:
    return data_dir() / "discord"


def snowflake_time(message_id: str | int) -> pd.Timestamp:
    ms = (int(message_id) >> 22) + DISCORD_EPOCH_MS
    return pd.Timestamp(ms, unit="ms", tz="UTC")


def latest_export(channel_id: str) -> Path:
    files = sorted((root() / "raw").glob(f"{channel_id}_*.json"))
    if not files:
        raise FileNotFoundError(f"no export for channel {channel_id} under {root() / 'raw'}")
    return files[-1]


def parse_export(raw: dict) -> pd.DataFrame:
    """One row per message: id, ts (New York), author, is_bot, content, reply_to (the
    replied-to message id or None), edited_ts, n_attachments, n_embeds."""
    rows = []
    for m in raw["messages"]:
        ref = m.get("reference") or {}
        rows.append(
            {
                "id": str(m["id"]),
                "ts": snowflake_time(m["id"]).tz_convert(TZ),
                "export_ts": pd.Timestamp(m["timestamp"]),
                "author": m["author"]["name"],
                "is_bot": bool(m["author"].get("isBot")),
                "content": m.get("content") or "",
                "reply_to": str(ref["messageId"]) if ref.get("messageId") else None,
                "edited_ts": pd.Timestamp(m["timestampEdited"])
                if m.get("timestampEdited")
                else None,
                "n_attachments": len(m.get("attachments") or []),
                "n_embeds": len(m.get("embeds") or []),
            }
        )
    cols = ["id", "ts", "export_ts", "author", "is_bot", "content", "reply_to", "edited_ts"]
    df = pd.DataFrame(rows, columns=[*cols, "n_attachments", "n_embeds"])
    # offsets mix EST/EDT and some times lack milliseconds
    exported = pd.to_datetime(df["export_ts"].astype(str), utc=True, format="ISO8601")
    skew = (df["ts"] - exported).abs().dt.total_seconds()
    if len(df) and skew.max() > 1:
        raise ValueError(f"snowflake and export timestamps disagree by up to {skew.max():.0f}s")
    df = df.drop(columns="export_ts").sort_values("ts", ignore_index=True)
    df["reply_to"] = df["reply_to"].astype(object).where(df["reply_to"].notna(), None)
    return df


def load(channel_id: str, path: Path | None = None) -> pd.DataFrame:
    path = path or latest_export(channel_id)
    return parse_export(json.loads(path.read_text(encoding="utf-8")))
