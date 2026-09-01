"""JSON schema for the brief payload, plus the cheap guards from the README.

The schema is what the API enforces (structured outputs). The guards are the
semantic checks a JSON schema cannot express -- structured outputs does not
support numeric or length constraints, so widths, stat lengths and counts are
checked here instead.
"""

from __future__ import annotations

from render import display_len


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": required if required is not None else list(props),
        "additionalProperties": False,
    }


_STR = {"type": "string"}
_STRS = {"type": "array", "items": _STR}

# One variant per block type. The "type" const is the discriminator.
BLOCK_VARIANTS = {
    "heading": _obj({"type": {"const": "heading"}, "text": _STR}),
    "subheading": _obj({"type": {"const": "subheading"}, "text": _STR}),
    "part": _obj({"type": {"const": "part"}, "label": _STR, "text": _STR}),
    "paragraph": _obj({"type": {"const": "paragraph"}, "text": _STR}),
    "bullets": _obj({"type": {"const": "bullets"}, "items": _STRS}),
    "facts": _obj({
        "type": {"const": "facts"},
        "rows": {"type": "array", "items": _STRS},
    }),
    "table": _obj({
        "type": {"const": "table"},
        "header": _STRS,
        "rows": {"type": "array", "items": _STRS},
        "widths": {"type": "array", "items": {"type": "number"}},
    }),
    "callout": _obj({"type": {"const": "callout"}, "title": _STR, "text": _STR}),
}

BRIEF_SCHEMA = _obj({
    "meta": _obj({
        "company": _STR,
        "kicker": _STR,
        "subtitle": _STR,
        "compiled": {"type": "string", "format": "date"},
        "confidence": {"enum": ["high", "medium", "low"]},
        "confidence_note": _STR,
    }),
    "stats": {
        "type": "array",
        "items": _obj({"value": _STR, "label": _STR}),
    },
    "blocks": {"type": "array", "items": {"anyOf": list(BLOCK_VARIANTS.values())}},
    "sources": _STR,
    # People worth writing to. source_url is required, so an unsourced person
    # cannot be expressed: no source means no entry. Empty is allowed for the
    # same reason unverified has no minItems. No email field, on purpose.
    "contacts": {
        "type": "array",
        "items": _obj({
            "name": _STR,
            "role": _STR,
            "why_them": _STR,
            "source_url": _STR,
            "confidence": {"enum": ["high", "medium", "low"]},
        }),
    },
    # Deliberately no minItems. An empty list is the overclaiming signal the
    # README asks us to retry on -- forcing the schema to fill it would only
    # buy a fabricated entry.
    "unverified": _STRS,
})

MAX_STAT_CHARS = 10
WIDTH_TOLERANCE = 0.01


def guards(data: dict) -> list[str]:
    """Return human-readable warnings. Never raises; never mutates."""
    warnings: list[str] = []

    stats = data.get("stats", [])
    if not 3 <= len(stats) <= 6:
        warnings.append(f"stats: {len(stats)} entries, README asks for 3-6")
    for s in stats:
        value = s.get("value", "")
        # Printed length, not source length: "13&ndash;16" is five characters
        # on the page, and entities are the documented way to write them.
        shown = display_len(value)
        if shown > MAX_STAT_CHARS:
            warnings.append(
                f"stats: value {value!r} prints as {shown} chars "
                f"(over {MAX_STAT_CHARS}); may not fit on one line"
            )

    callouts = 0
    for i, block in enumerate(data.get("blocks", [])):
        kind = block.get("type")
        where = f"blocks[{i}] ({kind})"
        if kind not in BLOCK_VARIANTS:
            warnings.append(f"{where}: unrecognised block type, will not render")
            continue
        if kind == "callout":
            callouts += 1
        if kind == "table":
            header, widths = block.get("header", []), block.get("widths", [])
            total = sum(widths)
            if abs(total - 1.0) > WIDTH_TOLERANCE:
                warnings.append(f"{where}: widths sum to {total:.3f}, not 1.0")
            if len(widths) != len(header):
                warnings.append(
                    f"{where}: {len(widths)} widths for {len(header)} columns"
                )
            for r, row in enumerate(block.get("rows", [])):
                if len(row) != len(header):
                    warnings.append(
                        f"{where}: row {r} has {len(row)} cells, "
                        f"header has {len(header)}"
                    )
        if kind == "facts":
            for r, row in enumerate(block.get("rows", [])):
                if len(row) != 2:
                    warnings.append(f"{where}: row {r} has {len(row)} cells, expected 2")

    if callouts > 2:
        warnings.append(f"blocks: {callouts} callouts, README caps them at 2")

    contacts = data.get("contacts", [])
    if not contacts:
        warnings.append("contacts: none found -- check unverified for why")
    for i, c in enumerate(contacts):
        if not str(c.get("source_url", "")).startswith(("http://", "https://")):
            warnings.append(f"contacts[{i}]: source_url is not a URL")

    return warnings


def overclaiming(data: dict) -> bool:
    """The one condition the README says to retry on."""
    return not data.get("unverified")
