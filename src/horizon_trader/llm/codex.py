"""Headless OpenAI Codex CLI (`codex exec`) as an LLM backend, the twin of `claude -p`.

Uses this user's ChatGPT login (`codex login`), no API key. Every call runs from an empty temp
directory with the user's config.toml (MCP servers, default model) and exec-policy rules ignored,
a read-only sandbox, and no session files.

Tools: Codex's web search only works through its code-mode host, so a call with `web=True` keeps
code mode (still read-only) and turns live web search on. A call with `web=False` turns code mode,
the shell, apps, browsers, sub-agents and web search off: checked 2026-11-05 that the model then
can't look up yesterday's SPY close, so it can only read the prompt.

OpenAI's structured output needs `additionalProperties: false` on every object, so schemas are
passed through `strict_schema` (it adds that and changes nothing else).
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

DEFAULT_EFFORT = "high"
# Features that give the model a way out of the prompt (codex features list, v0.162).
NO_TOOLS = [
    "shell_tool", "unified_exec", "apps", "browser_use", "browser_use_external", "computer_use",
    "collaboration_modes", "goals", "image_generation", "multi_agent", "plugins", "plugin_sharing",
    "remote_plugin", "skill_search", "skill_mcp_dependency_install", "view_image",
]  # fmt: skip


def is_codex_model(model: str) -> bool:
    """Claude models go to `claude -p`; anything else (gpt-*, o*) to Codex."""
    return not model.startswith("claude")


def strict_schema(schema: dict) -> dict:
    out = copy.deepcopy(schema)

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node.setdefault("additionalProperties", False)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(out)
    return out


def codex_cmd(model: str, web: bool, schema_path: Path | None, last_path: Path,
              effort: str = DEFAULT_EFFORT) -> list[str]:  # fmt: skip
    cmd = ["codex", "exec", "-m", model, "--ignore-user-config", "--ignore-rules",
           "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "--json",
           "-c", f"model_reasoning_effort={effort}",
           "-c", f"web_search={'live' if web else 'disabled'}"]  # fmt: skip
    for f in NO_TOOLS + ([] if web else ["code_mode_host"]):
        cmd += ["--disable", f]
    if schema_path is not None:
        cmd += ["--output-schema", str(schema_path)]
    return cmd + ["-o", str(last_path), "-"]


def parse_events(stdout: str) -> dict:
    """Usage totals, web searches and errors from the `--json` event stream."""
    usage, searches, errors = {}, 0, []
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        if isinstance(ev.get("usage"), dict):
            usage = ev["usage"]
        item = ev.get("item") if isinstance(ev.get("item"), dict) else {}
        if item.get("type") == "web_search" and ev.get("type") == "item.completed":
            searches += 1
        if ev.get("type") in ("error", "turn.failed"):
            errors.append(str(ev.get("message") or ev.get("error"))[:300])
    return {"usage": usage, "web_searches": searches, "errors": errors}


def codex(prompt: str, model: str, web: bool = False, schema: dict | None = None,
          effort: str = DEFAULT_EFFORT, timeout: int = 1800) -> dict:  # fmt: skip
    """One headless call. Returns a wrapper shaped like `claude -p --output-format json`:
    `result` (final text) and, with a schema, `structured_output`, plus Codex's own fields."""
    with tempfile.TemporaryDirectory(prefix="ht-codex-") as tmp:
        work = Path(tmp)
        schema_path = None
        if schema is not None:
            schema_path = work / "schema.json"
            schema_path.write_text(json.dumps(strict_schema(schema)), encoding="utf-8")
        last = work / "last.txt"
        cmd = codex_cmd(model, web, schema_path, last, effort)
        cmd[0] = shutil.which(cmd[0]) or cmd[0]  # Windows: npm installs codex as codex.cmd
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True,
            text=True, encoding="utf-8", timeout=timeout, check=False, cwd=work,
        )  # fmt: skip
        result = last.read_text(encoding="utf-8").strip() if last.exists() else ""
    if proc.returncode != 0 or not result:
        raise RuntimeError(f"codex exec exit {proc.returncode}: {(proc.stderr or result)[-300:]}")
    wrapper = {"backend": "codex exec", "model": model, "reasoning_effort": effort, "web": web,
               "result": result, **parse_events(proc.stdout)}  # fmt: skip
    if schema is not None:
        wrapper["structured_output"] = json.loads(result)
    return wrapper
