"""Per-model token pricing (USD per 1M tokens) and cost estimation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input_per_m: float
    output_per_m: float


PRICES: dict[str, Price] = {
    "claude-sonnet-5-5": Price(2.0, 10.0),
    "claude-opus-5-5": Price(4.0, 20.0),
    "claude-haiku-4-5": Price(1.0, 5.0),
    "sonnet": Price(2.0, 10.0),
    "opus": Price(4.0, 20.0),
    "haiku": Price(1.0, 5.0),
    "gemini-2.5-flash": Price(0.30, 2.50),
    "gemini-2.5-pro": Price(1.25, 10.0),
}
DEFAULT_PRICE = PRICES["sonnet"]


def price_for(model: str) -> Price:
    if model in PRICES:
        return PRICES[model]
    for key, price in PRICES.items():
        if model.startswith(key):
            return price
    return DEFAULT_PRICE


def estimate_cost_usd(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    if input_tokens is None and output_tokens is None:
        return None
    p = price_for(model)
    return round(((input_tokens or 0) * p.input_per_m + (output_tokens or 0) * p.output_per_m) / 1_000_000, 6)
