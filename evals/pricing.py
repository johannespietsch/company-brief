"""Prices and cost arithmetic.

Source: https://platform.claude.com/docs/en/about-claude/pricing (fetched 2026-09-01).
USD per million tokens, except server tools which are per call.

Two things worth knowing, both from that page:
  - web fetch costs nothing beyond the tokens the fetched page adds to context;
  - code execution is free when web_search_20260209 / web_fetch_20260209 is in
    the request, which is why the brief's research turn has no container cost.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PRICES_FETCHED = "2026-09-01"


@dataclass(frozen=True)
class ModelPrice:
    input: float
    output: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float


MODEL_PRICES: dict[str, ModelPrice] = {
    "claude-opus-5":    ModelPrice(5.0, 25.0, 6.25, 10.0, 0.50),
    "claude-opus-4-8":  ModelPrice(5.0, 25.0, 6.25, 10.0, 0.50),
    "claude-opus-4-7":  ModelPrice(5.0, 25.0, 6.25, 10.0, 0.50),
    "claude-opus-4-6":  ModelPrice(5.0, 25.0, 6.25, 10.0, 0.50),
    "claude-sonnet-5":  ModelPrice(2.0, 10.0, 2.50, 4.0, 0.20),
    "claude-sonnet-4-6": ModelPrice(3.0, 15.0, 3.75, 6.0, 0.30),
    "claude-haiku-4-5": ModelPrice(1.0, 5.0, 1.25, 2.0, 0.10),
    "claude-fable-5":   ModelPrice(10.0, 50.0, 12.50, 20.0, 1.00),
}

WEB_SEARCH_PER_CALL = 10.0 / 1000    # $10 per 1,000 searches
WEB_FETCH_PER_CALL = 0.0             # no additional charge


@dataclass
class Usage:
    """Accumulated usage across every billed request in one brief.

    The research turn makes several API calls -- pause_turn resumes and the
    overclaiming retry are separate billed requests -- so these must be summed,
    not read off the final response.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
    web_searches: int = 0
    web_fetches: int = 0
    requests: int = 0
    seconds: float = 0.0
    stop_reasons: list[str] = field(default_factory=list)

    def add_response(self, response) -> None:
        u = response.usage
        self.requests += 1
        self.input_tokens += getattr(u, "input_tokens", 0) or 0
        self.output_tokens += getattr(u, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(u, "cache_read_input_tokens", 0) or 0

        # cache_creation splits 5m/1h on current models; fall back to the flat
        # field and price it as a 5m write.
        created = getattr(u, "cache_creation", None)
        if created is not None:
            self.cache_write_5m_tokens += getattr(created, "ephemeral_5m_input_tokens", 0) or 0
            self.cache_write_1h_tokens += getattr(created, "ephemeral_1h_input_tokens", 0) or 0
        else:
            self.cache_write_5m_tokens += getattr(u, "cache_creation_input_tokens", 0) or 0

        server = getattr(u, "server_tool_use", None)
        if server is not None:
            self.web_searches += getattr(server, "web_search_requests", 0) or 0
            self.web_fetches += getattr(server, "web_fetch_requests", 0) or 0

        if response.stop_reason:
            self.stop_reasons.append(response.stop_reason)

    def as_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_5m_tokens": self.cache_write_5m_tokens,
            "cache_write_1h_tokens": self.cache_write_1h_tokens,
            "web_searches": self.web_searches,
            "web_fetches": self.web_fetches,
            "requests": self.requests,
            "seconds": round(self.seconds, 1),
            "stop_reasons": self.stop_reasons,
        }


class UnknownModel(KeyError):
    pass


def cost(usage: Usage, model: str) -> dict[str, float]:
    """Itemised USD cost. Raises rather than guessing at an unknown model."""
    try:
        p = MODEL_PRICES[model]
    except KeyError:
        raise UnknownModel(
            f"no price for {model!r}; add it to MODEL_PRICES from the pricing page"
        ) from None

    m = 1_000_000
    items = {
        "input": usage.input_tokens * p.input / m,
        "output": usage.output_tokens * p.output / m,
        "cache_read": usage.cache_read_tokens * p.cache_read / m,
        "cache_write": (usage.cache_write_5m_tokens * p.cache_write_5m
                        + usage.cache_write_1h_tokens * p.cache_write_1h) / m,
        "web_search": usage.web_searches * WEB_SEARCH_PER_CALL,
        "web_fetch": usage.web_fetches * WEB_FETCH_PER_CALL,
    }
    items["total"] = sum(items.values())
    return {k: round(v, 6) for k, v in items.items()}


def fmt(dollars: float) -> str:
    return f"${dollars:,.4f}" if dollars < 0.1 else f"${dollars:,.2f}"
