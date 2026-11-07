"""Push alerts to the owner: a Discord channel webhook and/or ntfy, whichever .env configures.

    DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...   # channel settings > Integrations
    DISCORD_USER_ID=123456789012345678                         # optional: @mention on urgent alerts
    NTFY_TOPIC=<long random topic>                              # optional second channel
    NTFY_URL=https://ntfy.sh                                    # optional, for a self-hosted server

    uv run python -m horizon_trader.ops.notify "test" "hello from the mini"   # send a test alert

Levels: "info" (no mention, e.g. the daily all-OK), "warn" (no mention), "urgent" (@mention, ntfy
high priority). The webhook URL is a secret: anyone with it can post to the channel. Webhooks
are send-only; nothing here reads Discord or talks to a broker.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

import horizon_trader.config  # noqa: F401  (loads .env)

LEVELS = ("info", "warn", "urgent")
ICONS = {"info": "✅", "warn": "⚠️", "urgent": "\U0001f6a8"}
DISCORD_LIMIT = 2000  # characters per message
USER_AGENT = "horizon-trader-alerts/1.0"  # Discord's edge rejects urllib's default agent


def channels() -> list[str]:
    out = []
    if os.environ.get("DISCORD_WEBHOOK_URL"):
        out.append("discord")
    if os.environ.get("NTFY_TOPIC"):
        out.append("ntfy")
    return out


def discord_payload(title: str, body: str, level: str, user_id: str | None) -> dict:
    """One message: mention (urgent only), bold title, body in a code block, within 2000 chars."""
    mention = f"<@{user_id}> " if user_id and level == "urgent" else ""
    head = f"{mention}{ICONS[level]} **{title}**"
    if not body:
        content = head
    else:
        room = DISCORD_LIMIT - len(head) - len("\n```\n\n```") - 20
        text = body if len(body) <= room else "...\n" + body[-room:]  # keep the end of a log
        content = f"{head}\n```\n{text.replace('```', "'''")}\n```"
    return {
        "content": content,
        "allowed_mentions": {"users": [user_id] if mention else []},
    }


def _post(url: str, data: bytes, headers: dict) -> None:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        resp.read()


def send(title: str, body: str = "", level: str = "warn", post=None) -> list[str]:
    """Send to every configured channel; returns the channels that worked. Raises SystemExit
    when none is configured, RuntimeError when every configured channel failed."""
    post = post or _post
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, not {level!r}")
    configured = channels()
    if not configured:
        raise SystemExit("no alert channel: set DISCORD_WEBHOOK_URL and/or NTFY_TOPIC in .env")
    sent, errors = [], []
    if "discord" in configured:
        payload = discord_payload(title, body, level, os.environ.get("DISCORD_USER_ID") or None)
        try:
            post(
                os.environ["DISCORD_WEBHOOK_URL"],
                json.dumps(payload).encode("utf-8"),
                {"Content-Type": "application/json", "User-Agent": USER_AGENT},
            )
            sent.append("discord")
        except Exception as exc:  # noqa: BLE001 - try the other channel
            errors.append(f"discord: {exc!r}")
    if "ntfy" in configured:
        url = os.environ.get("NTFY_URL", "https://ntfy.sh").rstrip("/") + "/"
        priority = {"info": "low", "warn": "default", "urgent": "high"}[level]
        try:
            post(
                url + os.environ["NTFY_TOPIC"],
                body.encode("utf-8")[:4000],
                {
                    "Title": title.encode("ascii", "replace").decode(),
                    "Priority": priority,
                    "Tags": "warning" if level != "info" else "white_check_mark",
                    "User-Agent": USER_AGENT,
                },
            )
            sent.append("ntfy")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"ntfy: {exc!r}")
    for e in errors:
        print(f"alert channel failed: {e}", file=sys.stderr)
    if not sent:
        raise RuntimeError("every alert channel failed: " + "; ".join(errors))
    return sent


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        raise SystemExit('usage: python -m horizon_trader.ops.notify "title" ["body"] [level]')
    title, body = args[0], args[1] if len(args) > 1 else ""
    level = args[2] if len(args) > 2 else "urgent"
    print("sent to", ", ".join(send(title, body, level)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
