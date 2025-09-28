from __future__ import annotations

from app.llm.client import LLMClient


async def summarise_to_500_words(llm: LLMClient, text: str) -> str:
    """Produce a <=500-word summary using the configured summariser model."""

    return await llm.summarise(text, max_words=500)
