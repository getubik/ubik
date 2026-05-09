"""
LLM adapter base — vendor-agnostic chat protocol.

The adapter pattern lets Ubik swap LLM providers (Z.AI / OpenAI /
Anthropic / Bedrock / local) by config, without touching the
researcher or executor code.

Two layers:
  • LLMAdapter — minimal `chat(messages)` interface
  • Implementations live in sibling files (`litellm_adapter.py` etc.)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(slots=True)
class Message:
    """A single chat message."""
    role: Literal["system", "user", "assistant", "tool"]
    content: str


@dataclass(slots=True)
class LLMResponse:
    """The result of a chat call."""
    text: str
    """The assistant's natural-language reply."""

    model: str
    """The model identifier the provider reported."""

    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    """Token usage. Zero when the provider doesn't report it."""

    finish_reason: str | None = None
    """e.g. 'stop', 'length', 'tool_calls', 'content_filter'."""

    raw: dict[str, Any] = field(default_factory=dict)
    """Pass-through of the provider's raw response, for debugging."""


class LLMAdapter(Protocol):
    """The minimal contract every LLM provider implementation must satisfy."""

    name: str
    """Short identifier, e.g. 'litellm', 'z-ai-direct', 'ollama-local'."""

    async def chat(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        thinking: bool = False,
    ) -> LLMResponse:
        """Send a chat request, return the response.

        ``thinking=True`` enables extended thinking on supported models
        (GLM-5.1, Claude Opus 4.7, …). Adapters that don't support it
        ignore the flag silently.
        """
        ...
