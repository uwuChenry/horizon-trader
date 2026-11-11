"""ops.notify (Discord/ntfy alerts) and ops.logins (login checks), with no network or CLIs."""

import json
import subprocess

import pytest

from horizon_trader.ops import logins as L
from horizon_trader.ops import notify as N

HOOK = "https://discord.com/api/webhooks/1/fake"


def capture(monkeypatch):
    sent = []
    monkeypatch.setattr(N, "_post", lambda url, data, headers: sent.append((url, data, headers)))
    return sent


def test_discord_urgent_mentions_owner(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", HOOK)
    monkeypatch.setenv("DISCORD_USER_ID", "42")
    sent = capture(monkeypatch)
    assert N.send("job failed", "log tail", "urgent") == ["discord"]
    url, data, headers = sent[0]
    payload = json.loads(data)
    assert url == HOOK and headers["User-Agent"] == N.USER_AGENT
    assert payload["content"].startswith("<@42> ") and "**job failed**" in payload["content"]
    assert payload["allowed_mentions"] == {"users": ["42"]}


@pytest.mark.parametrize("level", ["info", "warn"])
def test_discord_non_urgent_never_mentions(monkeypatch, level):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", HOOK)
    monkeypatch.setenv("DISCORD_USER_ID", "42")
    sent = capture(monkeypatch)
    N.send("t", "b", level)
    payload = json.loads(sent[0][1])
    assert "<@" not in payload["content"] and payload["allowed_mentions"] == {"users": []}


def test_long_body_keeps_the_end_within_limit():
    body = "\n".join(f"line {i}" for i in range(2000))
    content = N.discord_payload("t", body, "urgent", "42")["content"]
    assert len(content) <= N.DISCORD_LIMIT
    assert "line 1999" in content and "line 0\n" not in content


def test_code_fences_in_body_cannot_break_the_block():
    content = N.discord_payload("t", "a ``` b", "warn", None)["content"]
    assert content.count("```") == 2


def test_both_channels_and_one_failing(monkeypatch, capsys):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", HOOK)
    monkeypatch.setenv("NTFY_TOPIC", "topic")
    calls = []

    def post(url, data, headers):
        calls.append(url)
        if "discord" in url:
            raise OSError("down")

    monkeypatch.setattr(N, "_post", post)
    assert N.send("t", "b", "urgent") == ["ntfy"]
    assert len(calls) == 2 and "discord: OSError" in capsys.readouterr().err


def test_every_channel_failing_raises(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "topic")
    monkeypatch.setattr(N, "_post", lambda *a: (_ for _ in ()).throw(OSError("down")))
    with pytest.raises(RuntimeError, match="every alert channel failed"):
        N.send("t", "b")


def test_no_channel_refuses():
    with pytest.raises(SystemExit, match="DISCORD_WEBHOOK_URL"):
        N.send("t", "b")


def test_bad_level_refuses(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "topic")
    with pytest.raises(ValueError):
        N.send("t", "b", "loud")


class FakeIB:
    def __init__(self, accounts):
        self.accounts, self.closed = accounts, False

    def managedAccounts(self):
        return self.accounts

    def disconnect(self):
        self.closed = True


def test_gateway_paper_account_ok():
    ib = FakeIB(["DU123"])
    seen = {}

    def connect(readonly, client_id):
        seen.update(readonly=readonly, client_id=client_id)
        return ib

    r = L.ib_gateway(connect)
    assert r["status"] == "ok" and ib.closed
    assert seen == {"readonly": True, "client_id": L.GATEWAY_CLIENT_ID}


@pytest.mark.parametrize("accounts, why", [([], "no account"), (["U999"], "not a paper")])
def test_gateway_bad_accounts(accounts, why):
    r = L.ib_gateway(lambda **k: FakeIB(accounts))
    assert r["status"] == "bad" and why in r["detail"]


def test_gateway_down():
    def connect(**k):
        raise ConnectionRefusedError("refused")

    r = L.ib_gateway(connect)
    assert r["status"] == "bad" and "ConnectionRefusedError" in r["detail"]


def proc(stdout="", rc=0, stderr=""):
    return subprocess.CompletedProcess([], rc, stdout, stderr)


@pytest.mark.parametrize(
    "out, rc, ok",
    [("Logged in using ChatGPT", 0, True), ("Not logged in", 1, False),
     ("Not logged in", 0, False), ("", 0, False)],
)  # fmt: skip
def test_codex_login(out, rc, ok):
    assert (L.codex_login(lambda cmd: proc(out, rc))["status"] == "ok") is ok


def test_codex_missing_cli():
    def run(cmd):
        raise FileNotFoundError("codex is not on PATH")

    assert L.codex_login(run)["status"] == "bad"


CLAUDE_OK = '{"loggedIn": true, "authMethod": "claude.ai"}'


@pytest.mark.parametrize("out, ok", [(CLAUDE_OK, True), ('{"loggedIn": false}', False),
                                     ("garbage", False)])  # fmt: skip
def test_claude_login(out, ok):
    assert (L.claude_login(lambda cmd: proc(out))["status"] == "ok") is ok


def test_canary():
    assert L.codex_canary(lambda *a, **k: {"result": "OK"})["status"] == "ok"
    assert L.codex_canary(lambda *a, **k: {"result": "I can't"})["status"] == "bad"

    def broken(*a, **k):
        raise RuntimeError("codex exec exit 1: 401 Unauthorized")

    r = L.codex_canary(broken)
    assert r["status"] == "bad" and "401" in r["detail"]


def test_alert_lists_fixes_and_is_quiet_when_ok():
    ok = L.row("IB Gateway", True, "connected")
    assert L.alert([ok]) is None
    title, body = L.alert([ok, L.row("Codex login", False, "Not logged in")])
    assert "Codex login" in title and "IB Gateway" not in title
    assert "codex login" in body


def test_main_notifies_urgent_and_exits_1(monkeypatch):
    sent = []
    monkeypatch.setattr(L, "run_checks", lambda canary: [L.row("IB Gateway", False, "down")])
    monkeypatch.setattr(N, "send", lambda t, b, level: sent.append(level) or ["discord"])
    assert L.main(["--notify"]) == 1
    assert sent == ["urgent"]
