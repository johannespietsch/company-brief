"""Deterministic quality signals for a brief. No model call, no judgement.

These do not tell you a brief is good. They tell you it is well-formed, the
right length, and not obviously overclaiming -- the things worth watching for
regression when the prompt pack changes.
"""

from __future__ import annotations

import math

import render
from schema import BLOCK_VARIANTS, guards


def measure(data: dict, target_pages: int | None = None) -> dict:
    blocks = data.get("blocks", [])
    kinds: dict[str, int] = {}
    for b in blocks:
        kinds[b.get("type", "?")] = kinds.get(b.get("type", "?"), 0) + 1

    words = sum(
        len(render.plain(b.get("text", "")).split())
        + sum(len(render.plain(i).split()) for i in b.get("items", []))
        + sum(len(render.plain(c).split()) for row in b.get("rows", []) for c in row)
        for b in blocks
    )

    warnings = guards(data)
    content_pages = render.estimate_pages(data)
    sheets = math.ceil(content_pages)

    m = {
        "blocks": len(blocks),
        "block_kinds": kinds,
        "unknown_blocks": sum(v for k, v in kinds.items() if k not in BLOCK_VARIANTS),
        "body_words": words,
        "stats": len(data.get("stats", [])),
        "unverified": len(data.get("unverified", [])),
        "contacts": len(data.get("contacts", [])),
        "sources_words": len(render.plain(data.get("sources", "")).split()),
        "confidence": data.get("meta", {}).get("confidence"),
        "content_pages": round(content_pages, 2),
        "sheets": sheets,
        "guard_warnings": len(warnings),
        "guard_detail": warnings,
        # The README's overclaiming signal.
        "overclaiming": not data.get("unverified"),
    }
    if target_pages:
        m["target_pages"] = target_pages
        m["pages_delta"] = sheets - target_pages
    return m
