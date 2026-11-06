import json
import subprocess

import pytest

from horizon_trader.agents import prompts
from horizon_trader.llm import codex as C
from horizon_trader.llm import fundamentals as LF


def test_strict_schema_closes_every_object_and_changes_nothing_else():
    for schema in (LF.SCHEMA, prompts.SCHEMA):
        strict = C.strict_schema(schema)
        assert "additionalProperties" not in json.dumps(schema)  # the original is untouched

        def objects(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    yield node
                for v in node.values():
                    yield from objects(v)
            elif isinstance(node, list):
                for v in node:
                    yield from objects(v)

        objs = list(objects(strict))
        assert objs and all(o["additionalProperties"] is False for o in objs)
        # OpenAI strict mode also needs every property required: already true of both schemas
        assert all(set(o["required"]) == set(o["properties"]) for o in objs)
        assert json.dumps(strict).replace(', "additionalProperties": false', "") == json.dumps(
            schema
        )


def test_codex_cmd_tools_off_and_web():
    off = C.codex_cmd("gpt-6.1-sol", False, None, C.Path("last.txt"))
    assert off[:4] == ["codex", "exec", "-m", "gpt-6.1-sol"]
    assert "--ignore-user-config" in off and off[off.index("-s") + 1] == "read-only"
    assert "web_search=disabled" in off and "code_mode_host" in off
    assert {"shell_tool", "unified_exec", "multi_agent"} <= set(off)
    assert off[-3:] == ["-o", "last.txt", "-"] and "--output-schema" not in off
    web = C.codex_cmd("gpt-6.1-sol", True, C.Path("s.json"), C.Path("last.txt"))
    assert "web_search=live" in web and "code_mode_host" not in web  # search needs code mode
    assert web[web.index("--output-schema") + 1] == "s.json"


def test_parse_events_reads_usage_searches_and_errors():
    lines = [
        json.dumps({"type": "item.completed", "item": {"type": "web_search"}}),
        json.dumps({"type": "item.started", "item": {"type": "web_search"}}),
        json.dumps({"type": "error", "message": "boom"}),
        "not json",
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 2}}),
    ]
    ev = C.parse_events("\n".join(lines))
    assert ev == {"usage": {"input_tokens": 5, "output_tokens": 2}, "web_searches": 1,
                  "errors": ["boom"]}  # fmt: skip


def test_codex_wraps_the_answer_like_claude(monkeypatch):
    seen = {}

    def fake_run(cmd, input, cwd, **kw):
        seen.update(cmd=cmd, input=input, cwd=cwd)
        schema = json.loads(C.Path(cmd[cmd.index("--output-schema") + 1]).read_text())
        seen["schema"] = schema
        C.Path(cmd[cmd.index("-o") + 1]).write_text('{"scores": []}', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(C.subprocess, "run", fake_run)
    w = C.codex("the prompt", "gpt-6.1-sol", schema=LF.SCHEMA)
    assert w["structured_output"] == {"scores": []} and w["backend"] == "codex exec"
    assert w["model"] == "gpt-6.1-sol" and w["reasoning_effort"] == C.DEFAULT_EFFORT
    assert seen["input"] == "the prompt" and seen["schema"]["additionalProperties"] is False
    assert C.Path(seen["cwd"]).name.startswith("ht-codex-")  # an empty temp dir, now removed
    assert not C.Path(seen["cwd"]).exists()


def test_codex_raises_on_failure_or_empty_answer(monkeypatch):
    monkeypatch.setattr(C.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 1, stdout="", stderr="not logged in"))  # fmt: skip
    with pytest.raises(RuntimeError, match="not logged in"):
        C.codex("p", "gpt-6.1-sol")
    monkeypatch.setattr(C.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, stdout="", stderr=""))  # fmt: skip
    with pytest.raises(RuntimeError):
        C.codex("p", "gpt-6.1-sol")


def test_is_codex_model():
    assert C.is_codex_model("gpt-6.1-sol") and not C.is_codex_model("claude-opus-5-5")
