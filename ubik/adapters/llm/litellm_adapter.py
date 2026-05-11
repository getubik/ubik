"""
litellm-based LLM adapter — covers ~100 providers via one wire format.

For Z.AI's GLM-5.1 (the Ubik default) we use the OpenAI-compatible
endpoint and pass model="openai/glm-5.1" to litellm. The same adapter
talks to Anthropic, OpenAI, Bedrock, Gemini, Groq, Cerebras, Ollama,
vLLM, and any other provider with a litellm shim.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from .base import LLMAdapter, LLMResponse, Message

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LiteLLMConfig:
    """Configuration for a litellm-routed adapter."""

    model: str
    """Model identifier in litellm's namespace.

    Z.AI / OpenAI-compatible : ``"openai/glm-5.1"``
    Anthropic native         : ``"claude-opus-4-7"``
    Bedrock                  : ``"bedrock/anthropic.claude-opus-4-7"``
    Local Ollama             : ``"ollama/llama3.1"``
    """

    base_url: str | None = None
    """OpenAI-compatible custom endpoint. Required for Z.AI, optional elsewhere."""

    api_key: str | None = None
    """Direct API key. Falls back to provider-conventional env var if None."""

    api_key_env: str | None = None
    """Name of an env var holding the key (preferred over inlining)."""


class LiteLLMAdapter(LLMAdapter):
    """Default Ubik LLM adapter — routes everything through litellm."""

    name = "litellm"

    def __init__(self, config: LiteLLMConfig) -> None:
        self.config = config

    @property
    def _resolved_api_key(self) -> str | None:
        if self.config.api_key:
            return self.config.api_key
        if self.config.api_key_env:
            value = os.environ.get(self.config.api_key_env)
            if not value:
                raise RuntimeError(
                    f"LLM adapter expects env var {self.config.api_key_env!r} but it's not set"
                )
            return value
        return None

    async def chat(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        thinking: bool = False,
    ) -> LLMResponse:
        # Lazy import — keeps `import ubik` cheap when LLM isn't used (e.g. CLI help).
        try:
            from litellm import acompletion
        except ImportError as e:
            raise RuntimeError(
                "litellm is not installed. Run: pip install psssst (already a core dep)"
            ) from e

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if self.config.base_url:
            payload["base_url"] = self.config.base_url
        if api_key := self._resolved_api_key:
            payload["api_key"] = api_key

        # Thinking — GLM-5.1 (and Claude) accept this through the
        # OpenAI-compatible JSON shape, but neither litellm's param
        # sanitizer nor the OpenAI client knows about it. Pass it
        # through `extra_body` and litellm will inject it into the
        # raw JSON request body verbatim. This is the documented
        # provider-specific escape hatch.
        if thinking:
            payload["extra_body"] = {"thinking": {"type": "enabled"}}

        logger.debug(
            "LLM call → model=%s thinking=%s msgs=%d",
            self.config.model,
            thinking,
            len(messages),
        )

        response = await acompletion(**payload)

        # litellm normalizes most provider responses to OpenAI shape.
        choice = response.choices[0]
        text = choice.message.content or ""
        finish = getattr(choice, "finish_reason", None)
        usage = getattr(response, "usage", None) or {}

        return LLMResponse(
            text=text,
            model=getattr(response, "model", self.config.model),
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            thinking_tokens=getattr(usage, "reasoning_tokens", 0) or 0,
            finish_reason=finish,
            raw=response.model_dump() if hasattr(response, "model_dump") else {},
        )


def llm_from_config(cfg: dict[str, Any]) -> LLMAdapter:
    """Build a LiteLLMAdapter from the `researcher.llm` block of ubik.yaml."""
    base_url = cfg.get("base_url")
    model = cfg["model"]

    # If a Z.AI-style base URL is given, prefix with "openai/" so litellm
    # knows to use the OpenAI-compatible client (which Z.AI implements).
    if base_url and not model.startswith(("openai/", "anthropic/", "bedrock/", "ollama/")):
        model = f"openai/{model}"

    return LiteLLMAdapter(
        LiteLLMConfig(
            model=model,
            base_url=base_url,
            api_key_env=cfg.get("api_key_env"),
        )
    )
