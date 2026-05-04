from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Any


@dataclass
class LLMResult:
    data: dict[str, Any]
    tokens_in: int
    tokens_out: int


class LLMProvider(Protocol):
    name: str

    def generate_json(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float,
        max_output_tokens: int,
        json_schema: dict,
    ) -> LLMResult: ...


def estimate_cost(tokens_in: int, tokens_out: int, provider: str, model: str) -> float:
    if provider == "openai":
        in_price = 0.15 / 1_000_000
        out_price = 0.60 / 1_000_000
        return round(tokens_in * in_price + tokens_out * out_price, 6)
    return 0.0
