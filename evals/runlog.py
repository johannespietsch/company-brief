"""Append-only JSONL log of every real research run."""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).parent / "runs.jsonl"


def append(row: dict, path: Path = LOG_PATH) -> None:
    row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **row}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read(path: Path = LOG_PATH) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue          # a truncated tail should not kill the report
    return rows


def prior(model: str, effort: str, cache: bool = True,
          path: Path = LOG_PATH) -> dict | None:
    """Median usage of past successful runs at this config, for cost estimation.

    Cached and uncached runs differ by ~4x on the same work, so they are never
    averaged together. Returns None until there are enough runs to be worth
    trusting.
    """
    rows = [r for r in read(path)
            if r.get("model") == model and r.get("effort") == effort
            # rows written before caching existed have no key: they are uncached
            and r.get("cache", False) == cache
            # CLI runs report a list-price figure over a different tool mix;
            # they would skew an API projection either way.
            and r.get("backend", "api") == "api"
            and r.get("ok") and r.get("usage")]
    if len(rows) < 3:
        return None
    med = lambda key: statistics.median(r["usage"].get(key, 0) for r in rows)  # noqa: E731
    return {
        "input_tokens": int(med("input_tokens")),
        "output_tokens": int(med("output_tokens")),
        "cache_read_tokens": int(med("cache_read_tokens")),
        "cache_write_5m_tokens": int(med("cache_write_5m_tokens")),
        "web_searches": int(med("web_searches")),
        "web_fetches": int(med("web_fetches")),
        "n": len(rows),
    }
