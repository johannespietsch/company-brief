"""The API call: system prompt + filled user prompt + web tools -> brief JSON."""

from __future__ import annotations

import json
import time

import anthropic

from client import make_client
from evals.pricing import Usage
from schema import BRIEF_SCHEMA, overclaiming

# web_search_20260209 / web_fetch_20260209 need Opus 4.6+ or Sonnet 4.6+.
# Older models take the basic _20250305 / _20250910 variants instead.
# `citations` is left off web_fetch by choice, not necessity: tools/check_citations.py
# confirms output_config.format accepts it. The brief attributes in prose and in the
# sources paragraph, so citation metadata would not reach the rendered document.
TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 25},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 15},
]

# At xhigh/max effort the guidance is max_tokens >= 64000 or the output
# truncates mid-thought.
MAX_TOKENS = 64000

# Streaming survives a long turn -- there is no total-duration limit to hit --
# but it does not survive silence. The transport's read timeout is the gap
# between bytes, so a connection that blackholes mid-stream keeps its socket
# ESTABLISHED and raises only after `read` seconds. That is what killed the
# 2026-09-15 run: 600s (the SDK default) of silence, one dead request,
# ~$1 unrecorded.
#
# 120s instead, deliberately aggressive. _collect resumes from the last
# completed tool result, so a false positive costs one extra request whose
# input is almost entirely cache reads; the old default cost the whole run.
# The other three values are the SDK's own defaults, left alone.
READ_TIMEOUT = 120

# A read timeout is raised from the transport while the stream is being
# iterated, not on the request path where the SDK would wrap it as
# APITimeoutError -- on 2026-09-15 it surfaced raw, as httpx2.ReadTimeout.
# httpx2 is the SDK's transitive dependency and not ours (requirements.txt asks
# only for anthropic>=1.0), so it is imported defensively: if the SDK ever
# swaps transports, stall recovery degrades to "not recognised as a stall"
# rather than failing at import.
STALL_ERRORS: tuple[type[BaseException], ...] = (anthropic.APITimeoutError, TimeoutError)
try:
    import httpx2

    STALL_ERRORS += (httpx2.TimeoutException,)
    REQUEST_TIMEOUT: object = httpx2.Timeout(
        connect=5.0, read=READ_TIMEOUT, write=600, pool=600)
except ImportError:                                 # pragma: no cover
    REQUEST_TIMEOUT = float(READ_TIMEOUT)           # applies to connect too

# The only safe place to cut a turn short and resume from it: every block
# before a completed server-tool result is a valid, self-contained prefix.
RESUME_BOUNDARY = {"web_search_tool_result", "web_fetch_tool_result"}

RETRY_NOTE = (
    "Your previous response returned an empty \"unverified\" array. On a real "
    "company that almost always means something is being overclaimed. Re-examine "
    "every figure, date and named customer, and list what you could not actually "
    "confirm from a source you retrieved, together with what would be needed to "
    "confirm it."
)


class ResearchError(RuntimeError):
    pass


class StreamStalled(RuntimeError):
    """A read timeout mid-stream, carrying the part of the turn worth keeping.

    `content` is truncated at the last completed server-tool result, which
    keeps the expensive half -- the searches and every fetched page already in
    context -- and drops only the cheap tail. What follows the cut is dropped
    on purpose, not for tidiness: an unpaired server_tool_use is an invalid
    request, a thinking block is unusable without the signature that arrives
    with its completion, and a partial text block would prefill half-written
    JSON into a schema-constrained turn.
    """

    def __init__(self, content: list, cause: BaseException):
        super().__init__(
            f"stream went silent for {READ_TIMEOUT}s ({type(cause).__name__}); "
            f"kept {len(content)} completed block(s)"
        )
        self.content = content


class Run:
    """One brief's worth of API activity: usage, timing, raw responses."""

    def __init__(self, model: str, effort: str):
        self.model = model
        self.effort = effort
        self.usage = Usage()
        self.responses: list = []
        self.attempts = 0

    def record(self, response) -> None:
        self.responses.append(response)
        self.usage.add_response(response)


# What a streamed content block means, for the progress line.
BLOCK_LABEL = {
    "thinking": "thinking",
    "text": "writing the brief",
    "web_search_tool_result": "search results in",
    "web_fetch_tool_result": "page fetched",
}


# web_search_20260209 / web_fetch_20260209 drive code_execution internally to
# filter results. Those blocks are neither billed as searches nor interesting
# here, so they are not counted and not printed.
COUNTED_TOOLS = {"web_search": "search", "web_fetch": "fetch"}


def _describe(block) -> str | None:
    """A short progress line for a completed content block, or None to stay quiet."""
    kind = getattr(block, "type", None)
    if kind == "server_tool_use":
        name = getattr(block, "name", "") or ""
        if name not in COUNTED_TOOLS:
            return None
        args = getattr(block, "input", None) or {}
        detail = args.get("query") or args.get("url") or ""
        return f"{name} {detail}".strip()
    return BLOCK_LABEL.get(kind)


def _system_blocks(system: str, cache: bool):
    """The system prompt is byte-identical across every request and every resume,
    so it gets an explicit breakpoint: a guaranteed read point that survives
    whatever the growing message tail does later."""
    if not cache:
        return system
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


def _stream_once(client, run: Run, *, system, messages, progress, cache=True):
    """One streamed request, emitting a progress line per completed block.

    get_final_message() alone blocks until the whole turn is done, which on a
    20-search brief is minutes of silence. Iterating the events first costs
    nothing and shows the run is alive.
    """
    started = time.monotonic()
    seen = {"search": 0, "fetch": 0}
    safe_upto = 0                       # blocks that survive a mid-stream stall
    kwargs = dict(
        model=run.model,
        max_tokens=MAX_TOKENS,
        system=_system_blocks(system, cache),
        messages=messages,
        tools=TOOLS,
        output_config={
            "effort": run.effort,
            "format": {"type": "json_schema", "schema": BRIEF_SCHEMA},
        },
        timeout=REQUEST_TIMEOUT,
    )
    if cache:
        # Automatic caching on the growing tail. The server tools insert their
        # own 5-minute cache write after each tool result once a request uses
        # caching at all, which is what turns the re-read of accumulated search
        # results from full price into cache reads.
        kwargs["cache_control"] = {"type": "ephemeral"}
    with client.messages.stream(**kwargs) as stream:
        try:
            for event in stream:
                if getattr(event, "type", None) != "content_block_stop":
                    continue
                block = getattr(event, "content_block", None)
                if block is None:                   # older SDKs: read the snapshot
                    try:
                        block = stream.current_message_snapshot.content[event.index]
                    except Exception:               # noqa: BLE001 - best-effort
                        continue
                kind = getattr(block, "type", None)
                # Tracked whether or not anyone is reading the progress lines,
                # which is why this no longer short-circuits on progress=None.
                if kind in RESUME_BOUNDARY:
                    safe_upto = event.index + 1
                if kind == "server_tool_use":
                    key = COUNTED_TOOLS.get(getattr(block, "name", "") or "")
                    if key:
                        seen[key] += 1
                line = _describe(block)
                if progress and line:
                    progress(f"[{time.monotonic() - started:5.0f}s] "
                             f"{seen['search']:2d} searches {seen['fetch']:2d} fetches  {line[:90]}")
            response = stream.get_final_message()
        except STALL_ERRORS as e:
            # This request was billed for whatever it produced before going
            # quiet, so the partial snapshot is recorded -- both to cost it and
            # to leave it on the partial cassette -- before the prefix is
            # handed back for the resume.
            kept: list = []
            try:
                snap = stream.current_message_snapshot
                run.record(snap)
                kept = list(snap.content[:safe_upto])
            except Exception:                       # noqa: BLE001 - nothing arrived at all
                pass
            run.usage.seconds += time.monotonic() - started
            raise StreamStalled(kept, e) from e
    run.usage.seconds += time.monotonic() - started
    return response


def _merge(messages: list, content) -> None:
    """Fold assistant content into the trailing assistant turn, or open one.

    A turn that paused or stalled is still one turn, and two adjacent assistant
    messages are not a valid request.
    """
    if messages and messages[-1]["role"] == "assistant":
        messages[-1]["content"] = list(messages[-1]["content"]) + list(content)
    else:
        messages.append({"role": "assistant", "content": list(content)})


def _collect(client, run: Run, *, system, messages, progress=None, cache=True,
             max_pause_resumes=5, max_stall_resumes=3):
    """Run one turn to completion, resuming across pause_turns and stalls.

    A paused turn comes back as stop_reason "pause_turn" with no error, so
    ignoring it would yield a silently truncated brief. Every resume is a
    separately billed request, so each one is recorded.

    Worth knowing: as of 2026-09-15 this has never actually happened. All six
    runs in evals/runs.jsonl finished in one request with stop_reason
    "end_turn", including one at 25 searches plus 15 fetches -- so the search
    budget in TOOLS stays under whatever the real iteration limit is. An
    earlier version of this docstring claimed a brief "reliably exceeds" that
    limit; the run log says otherwise. The path is kept because a paused turn
    is silent when it does happen, but treat it as unexercised against the
    live API, not as proven machinery.

    The two budgets are deliberately separate. A flaky connection and a
    search-hungry turn are different failure modes, and a single counter would
    let the first eat the allowance the second legitimately needs.
    """
    resumes = 0
    stalls = 0
    while True:
        try:
            response = _stream_once(client, run, system=system, messages=messages,
                                    progress=progress, cache=cache)
        except StreamStalled as stalled:
            stalls += 1
            if stalls > max_stall_resumes:
                raise ResearchError(
                    f"stream stalled {stalls} times ({READ_TIMEOUT}s of silence "
                    f"each); raise max_stall_resumes if the network is merely slow"
                ) from stalled
            if progress:
                progress(f"{stalled}; resuming ({stalls})")
            # An empty prefix means the stall landed before the first tool
            # result: there is nothing valid to hand back, so the same request
            # simply goes out again.
            if stalled.content:
                _merge(messages, stalled.content)
            continue

        run.record(response)
        _merge(messages, response.content)

        if response.stop_reason != "pause_turn":
            return response, messages

        resumes += 1
        if progress:
            progress(f"server-tool limit hit; resuming turn ({resumes})")
        if resumes > max_pause_resumes:
            raise ResearchError(
                f"turn still paused after {max_pause_resumes} resumes; "
                "raise max_pause_resumes or lower the search budget"
            )


def _payload(response) -> dict:
    if response.stop_reason == "refusal":
        raise ResearchError(f"model declined: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise ResearchError(
            f"output hit max_tokens ({MAX_TOKENS}); the JSON is truncated"
        )
    text = "".join(b.text for b in response.content if b.type == "text")
    if not text.strip():
        raise ResearchError(f"no text block in response (stop_reason={response.stop_reason})")
    # output_config.format guarantees this parses; if it ever does not, the
    # traceback is the honest signal.
    return json.loads(text)


def run(system: str, user: str, *, model: str, effort: str, retry: bool = True,
        progress=None, cache: bool = True, state: Run | None = None) -> tuple[dict, Run]:
    """Research one company. Returns (brief, Run) -- Run carries usage for costing.

    `state` lets the caller own the meter. Usage accumulates on it as each
    request finishes, so a caller holding the reference can still cost a run
    that died part-way; one is constructed here when omitted.
    """
    client = make_client()
    state = Run(model, effort) if state is None else state
    messages: list[dict] = [{"role": "user", "content": user}]

    response, messages = _collect(client, state, system=system, messages=messages,
                                  progress=progress, cache=cache)
    data = _payload(response)
    state.attempts = 1

    if retry and overclaiming(data):
        messages.append({"role": "user", "content": RETRY_NOTE})
        if progress:
            progress("unverified came back empty -- retrying once")
        response, messages = _collect(client, state, system=system, messages=messages,
                                      progress=progress, cache=cache)
        data = _payload(response)
        state.attempts = 2

    return data, state
