#!/usr/bin/env python3
"""Does output_config.format survive alongside web_search / web_fetch?

Structured outputs is documented as incompatible with *citations* (400). Web
search results carry citation metadata, so this checks empirically whether the
combination research.py uses is actually accepted.

Runs four small live requests (a few cents total):
  1. schema only, no tools          -- control
  2. schema + web_search            -- the combination we depend on
  3. schema + web_search + web_fetch-- what research.py actually sends
  4. schema + web_fetch(citations)  -- the combination expected to 400

    .venv/bin/python tools/check_citations.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from client import make_client          # noqa: E402
from evals.pricing import Usage, cost, fmt  # noqa: E402

MODEL = "claude-opus-5"
SPEND: list[float] = []
SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "confidence": {"enum": ["high", "medium", "low"]},
    },
    "required": ["answer", "confidence"],
    "additionalProperties": False,
}

SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 2}
FETCH = {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 1}
FETCH_CITED = {**FETCH, "citations": {"enabled": True}}

CASES = [
    ("schema only (control)", None,
     "What is 2+2? Answer in the given format."),
    ("schema + web_search", [SEARCH],
     "Search for Anthropic's headquarters city. Answer in the given format."),
    ("schema + web_search + web_fetch", [SEARCH, FETCH],
     "Search for Anthropic's headquarters city, fetch a page confirming it, "
     "then answer in the given format."),
    ("schema + web_fetch(citations=on)", [SEARCH, FETCH_CITED],
     "Search for Anthropic's headquarters city, fetch a page confirming it, "
     "then answer in the given format."),
]


def run(client, label, tools, prompt) -> bool:
    kwargs = dict(
        model=MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    if tools:
        kwargs["tools"] = tools
    try:
        with client.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()
    except anthropic.APIStatusError as e:
        print(f"  {label:34} HTTP {e.status_code}")
        body = str(getattr(e, "message", e))
        print(f"  {'':34} {body[:300]}")
        return False

    text = "".join(b.text for b in msg.content if b.type == "text")
    u = Usage(); u.add_response(msg)
    SPEND.append(cost(u, MODEL)["total"])
    print(f"  {label:34} OK  stop={msg.stop_reason} searches={u.web_searches} "
          f"{fmt(SPEND[-1])}")
    print(f"  {'':34}     {text[:120]}")
    return True


def main() -> int:
    client = make_client()
    print(f"anthropic {anthropic.__version__}, model {MODEL}\n")
    results = {}
    for label, tools, prompt in CASES:
        results[label] = run(client, label, tools, prompt)
        print()
    print("summary:")
    for label, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    print(f"\ntotal spend on this check: {fmt(sum(SPEND))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
