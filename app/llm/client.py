from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from openai import AsyncOpenAI

from app.config import Settings, get_settings
from app.llm import prompts
from app.llm.prompts import Model1Context, Model2Context, Model3Context
from app.llm.schemas import MODEL3_JSON_SCHEMA, Model3Response
from app.llm.usage import UsageTracker


@dataclass(slots=True)
class LLMResult:
    text: str
    response: dict[str, Any]


def _extract_output_text(response: Any) -> str:
    if response is None:
        return ""

    if hasattr(response, "output_text") and response.output_text:
        return str(response.output_text)

    data = getattr(response, "model_dump", lambda: {})()
    output = data.get("output") or data.get("outputs")
    if isinstance(output, list):
        chunks: list[str] = []
        for item in output:
            content = item.get("content") if isinstance(item, dict) else None
            if not content and isinstance(item, list):
                content = item
            if isinstance(content, list):
                for part in content:
                    text = part.get("text") if isinstance(part, dict) else None
                    if text:
                        chunks.append(text)
            elif isinstance(content, dict):
                text = content.get("text")
                if text:
                    chunks.append(text)
        if chunks:
            return "\n".join(chunks).strip()

    if hasattr(response, "output"):
        output_attr = response.output
        if isinstance(output_attr, list):
            return "\n".join(str(item) for item in output_attr)

    return str(response)


def _response_to_dict(response: Any) -> dict[str, Any]:
    if response is None:
        return {}
    if isinstance(response, dict):
        return response
    model_dump = getattr(response, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    result: dict[str, Any] = {}
    for attr in ("model", "usage", "output", "output_text"):
        if hasattr(response, attr):
            result[attr] = getattr(response, attr)
    return result


class LLMClient:
    def __init__(
        self,
        *,
        settings: Optional[Settings] = None,
        usage_tracker: Optional[UsageTracker] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.usage = usage_tracker or UsageTracker()
        self._stub_mode = getattr(self.settings, "llm_stub_mode", False)
        self._client = AsyncOpenAI(api_key=self.settings.openai_api_key)

    async def close(self) -> None:
        await self._client.close()

    async def __aenter__(self) -> "LLMClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        await self.close()

    async def run_model1(self, context: Model1Context) -> LLMResult:
        if self._stub_mode:
            return LLMResult(text="Stub Daily Plan", response={"stub": True})
        response = await self._client.responses.create(
            model=self.settings.openai_responses_model_m1,
            input=[
                {"role": "system", "content": prompts.MODEL_1_SYSTEM_PROMPT},
                {"role": "user", "content": prompts.build_model1_user_prompt(context)},
            ],
            tools=[{"type": "web_search"}],
            reasoning={"effort": self.settings.openai_responses_reasoning_m1},
        )
        self.usage.add_response(response)
        return LLMResult(text=_extract_output_text(response), response=_response_to_dict(response))

    async def run_model2(self, context: Model2Context) -> LLMResult:
        if self._stub_mode:
            return LLMResult(text="Stub Model 2 Output", response={"stub": True})
        response = await self._client.responses.create(
            model=self.settings.openai_responses_model_m2,
            input=[
                {"role": "system", "content": prompts.MODEL_2_SYSTEM_PROMPT},
                {"role": "user", "content": prompts.build_model2_user_prompt(context)},
            ],
            tools=[{"type": "web_search"}],
            reasoning={"effort": self.settings.openai_responses_reasoning_m2},
        )
        self.usage.add_response(response)
        return LLMResult(text=_extract_output_text(response), response=_response_to_dict(response))

    async def run_model3(self, context: Model3Context) -> Model3Response:
        if self._stub_mode:
            return Model3Response.model_validate({"orders": []})

        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "model3_response",
                "schema": MODEL3_JSON_SCHEMA,
            },
        }
        response = await self._client.responses.create(
            model=self.settings.openai_responses_model_m3,
            input=[
                {"role": "system", "content": prompts.MODEL_3_SYSTEM_PROMPT},
                {"role": "user", "content": prompts.build_model3_user_prompt(context)},
            ],
            response_format=response_format,
            reasoning={"effort": self.settings.openai_responses_reasoning_m3},
        )
        self.usage.add_response(response)
        payload_text = _extract_output_text(response)
        return self._parse_model3_output(payload_text)

    async def summarise(self, text: str, *, max_words: int = 500) -> str:
        if self._stub_mode:
            return text[:400]
        prompt = f"Compress the following text into <= {max_words} words:\n\n{text}"
        response = await self._client.responses.create(
            model=self.settings.openai_responses_model_summariser,
            input=[
                {"role": "system", "content": prompts.SUMMARISER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            reasoning={"effort": self.settings.openai_responses_reasoning_summariser},
        )
        self.usage.add_response(response)
        return _extract_output_text(response)

    def _parse_model3_output(self, raw: str) -> Model3Response:
        if not raw:
            return Model3Response(orders=[])
        try:
            return Model3Response.model_validate_json(raw)
        except ValueError:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError("Model 3 output is not valid JSON") from exc
            return Model3Response.model_validate(data)
