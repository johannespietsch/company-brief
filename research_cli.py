"""The research turn via the Claude Code CLI instead of the API.

Same contract as research.run -- (brief, run state) -- so brief.py picks a
backend and nothing downstream changes. The CLI owns the agent loop, so none of
research.py's machinery is needed here: no streaming client, no pause_turn
resumes, no stall recovery, no cache breakpoints.

Billing is why this exists. The child process runs on whatever the CLI is
logged in with -- typically a Claude subscription -- and ANTHROPIC_API_KEY is
stripped from its environment, because brief.py loads .env and the CLI would
otherwise bill that key instead.

Two behaviours differ from the API path:
  - WebFetch hands the model a small-model digest of the page, not the page.
    The prompt's "read the primary source" rule is weaker here; compare a brief
    from each backend on the same company before relying on this one.
  - There is no per-tool budget like max_uses. The prompt's search budget is
    the only limit.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time

from evals.pricing import Usage
from research import RETRY_NOTE, ResearchError
from schema import BRIEF_SCHEMA, overclaiming

TOOLS = "WebSearch,WebFetch"
COUNTED_TOOLS = {"WebSearch": "search", "WebFetch": "fetch"}

# Credentials the CLI would prefer over its own login. Stripping them is what
# keeps a run on the subscription.
API_CREDENTIALS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


class Run:
    """One brief's worth of CLI activity.

    `responses` holds the raw stream-json events, in order, so the cassette
    records exactly what the CLI emitted. `cost_usd` is the CLI's own figure: a
    list-price equivalent, not a bill, and summed per invocation because a
    resumed session reports only its own cost.
    """

    def __init__(self, model: str, effort: str):
        self.model = model
        self.effort = effort
        self.usage = Usage()
        self.responses: list[dict] = []
        self.attempts = 0
        self.cost_usd = 0.0
        self.session_id: str | None = None

    def cost(self) -> dict[str, float]:
        return {"total": round(self.cost_usd, 6), "basis": "cli-list-price"}


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in API_CREDENTIALS}


def _command(run: Run, system: str, resume: str | None) -> list[str]:
    # --safe-mode keeps the user's CLAUDE.md, hooks, skills and MCP servers out
    # of the research turn; auth and built-in tools still work. The prompt goes
    # in on stdin: --tools is variadic and would swallow a trailing argument.
    cmd = [
        "claude", "-p", "--safe-mode",
        "--model", run.model, "--effort", run.effort,
        "--tools", TOOLS, "--allowedTools", TOOLS, "--permission-mode", "dontAsk",
        "--system-prompt", system,
        "--json-schema", json.dumps(BRIEF_SCHEMA),
        "--output-format", "stream-json", "--verbose",
    ]
    if resume:
        cmd += ["--resume", resume]
    return cmd


def _record_result(run: Run, result: dict) -> None:
    """Fold one invocation's result event into the meter.

    Tokens are summed across every model in modelUsage -- WebFetch digests run
    on a smaller model -- which is why cost comes from the CLI rather than from
    pricing.cost() at the brief's model rate.
    """
    u = run.usage
    for m in (result.get("modelUsage") or {}).values():
        u.input_tokens += m.get("inputTokens", 0) or 0
        u.output_tokens += m.get("outputTokens", 0) or 0
        u.cache_read_tokens += m.get("cacheReadInputTokens", 0) or 0
        u.cache_write_5m_tokens += m.get("cacheCreationEphemeral5mInputTokens", 0) or 0
        u.cache_write_1h_tokens += m.get("cacheCreationEphemeral1hInputTokens", 0) or 0
    u.stop_reasons.append(result.get("subtype", "?"))
    run.cost_usd += result.get("total_cost_usd", 0) or 0


def _invoke(run: Run, *, system: str, prompt: str, cwd: str,
            resume: str | None = None, progress=None) -> dict:
    """One CLI invocation, emitting a progress line per search or fetch.

    Searches and fetches are counted from the tool calls: the result's
    server_tool_use reports zero for CLI-side web tools.
    """
    if shutil.which("claude") is None:
        raise ResearchError("the `claude` CLI is not on PATH; install Claude Code "
                            "or use --backend api")
    started = time.monotonic()
    seen = {"search": 0, "fetch": 0}
    message_ids: set[str] = set()
    result = None
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as err:
        proc = subprocess.Popen(_command(run, system, resume), cwd=cwd, env=_env(),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=err, text=True, encoding="utf-8")
        proc.stdin.write(prompt)
        proc.stdin.close()
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            run.responses.append(event)
            kind = event.get("type")
            if kind == "result":
                result = event
            if kind != "assistant":
                continue
            message = event.get("message") or {}
            if message.get("id"):
                message_ids.add(message["id"])
            for block in message.get("content") or []:
                key = COUNTED_TOOLS.get(block.get("name", "")) if block.get("type") == "tool_use" else None
                if not key:
                    continue
                seen[key] += 1
                if progress:
                    args = block.get("input") or {}
                    detail = args.get("query") or args.get("url") or ""
                    progress(f"[{time.monotonic() - started:5.0f}s] "
                             f"{seen['search']:2d} searches {seen['fetch']:2d} fetches  "
                             f"{block['name']} {detail}"[:120])
        proc.wait()
        err.seek(0)
        stderr = err.read().strip()

    u = run.usage
    u.seconds += time.monotonic() - started
    u.requests += len(message_ids)
    u.web_searches += seen["search"]
    u.web_fetches += seen["fetch"]
    if result is None:
        raise ResearchError(f"claude exited {proc.returncode} without a result"
                            + (f": {stderr[-300:]}" if stderr else ""))
    _record_result(run, result)
    run.session_id = result.get("session_id") or run.session_id
    if result.get("is_error") or result.get("subtype") != "success":
        raise ResearchError(f"claude run failed ({result.get('subtype')}): "
                            f"{str(result.get('result') or result.get('errors'))[:300]}")
    data = result.get("structured_output")
    if not isinstance(data, dict):
        raise ResearchError("claude returned no structured output")
    return data


def run(system: str, user: str, *, model: str, effort: str, retry: bool = True,
        progress=None, cache: bool = True, state: Run | None = None) -> tuple[dict, Run]:
    """Research one company through the CLI. Same signature as research.run.

    `cache` is accepted for that symmetry and ignored: the CLI manages its own
    prompt caching. The overclaiming retry resumes the same session, so the
    second attempt sees everything the first one found. Each run gets its own
    scratch directory, which keeps these sessions out of any project's resume
    list; --resume needs the same directory, so it lives until the run ends.
    """
    state = Run(model, effort) if state is None else state
    cwd = tempfile.mkdtemp(prefix="company-brief-")
    try:
        data = _invoke(state, system=system, prompt=user, cwd=cwd, progress=progress)
        state.attempts = 1
        if retry and overclaiming(data):
            if progress:
                progress("unverified came back empty -- retrying once")
            data = _invoke(state, system=system, prompt=RETRY_NOTE, cwd=cwd,
                           resume=state.session_id, progress=progress)
            state.attempts = 2
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
    return data, state
