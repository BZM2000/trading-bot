from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional


@dataclass(slots=True)
class UsageRecord:
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass
class UsageTracker:
    records: list[UsageRecord] = field(default_factory=list)

    def add_response(self, response: Any) -> None:
        data = _response_to_dict(response)
        usage = data.get("usage") or {}
        model = data.get("model", "unknown")
        input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
        if total_tokens == 0 and not usage:
            return
        self.records.append(
            UsageRecord(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
            )
        )

    def merge(self, other: "UsageTracker") -> None:
        self.records.extend(other.records)

    def totals(self) -> dict[str, int]:
        total_input = sum(record.input_tokens for record in self.records)
        total_output = sum(record.output_tokens for record in self.records)
        total = sum(record.total_tokens for record in self.records)
        return {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "total_tokens": total,
            "requests": len(self.records),
        }

    def to_json(self) -> list[dict[str, int | str]]:
        return [
            {
                "model": record.model,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "total_tokens": record.total_tokens,
            }
            for record in self.records
        ]


def _response_to_dict(response: Any) -> dict[str, Any]:
    if response is None:
        return {}

    if isinstance(response, dict):
        return response

    model_dump = getattr(response, "model_dump", None)
    if callable(model_dump):
        return model_dump()

    data = {}
    for attr in ("model", "usage", "output", "output_text"):
        if hasattr(response, attr):
            data[attr] = getattr(response, attr)
    return data
