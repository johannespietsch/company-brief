"""Record the raw API responses of a real run; replay them for free.

A cassette makes a paid, non-deterministic research run into a fixture you can
re-parse, re-validate and re-render as often as you like. It is the difference
between iterating on render.py for free and paying for a fresh brief each time.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

CASSETTE_DIR = Path(__file__).parent / "cassettes"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "brief"


def path_for(company: str, model: str, effort: str, when=None,
             partial: bool = False) -> Path:
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    tail = "__partial" if partial else ""
    return CASSETTE_DIR / f"{slug(company)}__{slug(model)}__{effort}__{stamp}{tail}.json"


def save(path: Path, *, request: dict, responses: list,
         partial: bool = False) -> Path:
    """`responses` are anthropic Message objects, in call order -- or, from the
    CLI backend, its raw stream-json events, which are already plain dicts.

    `partial` marks a tape from a run that never produced a brief -- a stalled
    or errored fetch. It is evidence, not a fixture: the recorded text does not
    parse as a brief, so `replay` reports what is on the tape instead of trying.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "recorded": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "partial": partial,
        "request": request,
        "responses": [r if isinstance(r, dict) else r.model_dump(mode="json")
                      for r in responses],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def replay_text(cassette: dict) -> str:
    """Concatenated assistant text across the recorded responses.

    A CLI tape carries the brief as the last result event's structured_output
    rather than as text, so that wins when present.
    """
    results = [r for r in cassette["responses"]
               if r.get("type") == "result" and isinstance(r.get("structured_output"), dict)]
    if results:
        return json.dumps(results[-1]["structured_output"], ensure_ascii=False)
    out = []
    for resp in cassette["responses"]:
        for block in resp.get("content", []):
            if block.get("type") == "text":
                out.append(block.get("text", ""))
    return "".join(out)
