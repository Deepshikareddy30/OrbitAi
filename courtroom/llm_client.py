"""Minimal OpenRouter chat-completion client, shared by both Courtroom roles.

Two separate API keys/models (docs/DECISIONS.md) so Advocate and Challenger are
genuinely independent voices, not the same model arguing with itself.
"""

import logging
import os
import re

import httpx

log = logging.getLogger("courtroom.llm")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class CourtroomLLMError(Exception):
    """Raised on any call/parse failure - callers fall back to a template argument."""


def call(system_prompt: str, user_prompt: str, *, api_key: str, model: str,
        max_tokens: int = 600, timeout: float = 30.0) -> str:
    """Returns the model's text reply. Raises CourtroomLLMError on any failure (SPEC:
    handle function-calling/timeout errors gracefully - callers must catch this) -
    including a response that leaked visible chain-of-thought (docs/DECISIONS.md
    COURT2): "no chain-of-thought" is a hard requirement in both spec passes, and a
    small free reasoning model not reliably obeying that instruction is a real,
    observed failure mode, not a hypothetical - caught by actually running this against
    the real API, not by inspection. Safer to fall back to the honest template than
    show 500 words of "I need to argue FOR..." meta-commentary on a demo screen.
    """
    if not api_key:
        raise CourtroomLLMError("no API key configured")
    try:
        resp = httpx.post(
            OPENROUTER_URL, timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model, "temperature": 0.4, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"].get("content")
        if not content:
            # Reasoning-style free models (e.g. dots-3-note) can return empty `content`
            # with the answer only in `reasoning` if max_tokens cuts off before the
            # final answer - see docs/DECISIONS.md COURT1. Fall back to that.
            content = data["choices"][0]["message"].get("reasoning")
        if not content or not content.strip():
            raise CourtroomLLMError(f"empty response from {model}")
        content = _strip_markdown(content.strip())
        if _looks_like_leaked_reasoning(content):
            raise CourtroomLLMError(f"{model} leaked chain-of-thought instead of a direct answer")
        return content
    except CourtroomLLMError:
        raise
    except Exception as e:  # noqa: BLE001 - any network/parse failure degrades gracefully
        raise CourtroomLLMError(f"{model} call failed: {e}") from e


def _strip_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    return text.strip()


_REASONING_LEAK_PATTERNS = re.compile(
    r"\b(I need to|let me think|the instruction says|I must (?:use|respond|cite)|"
    r"I'm supposed to|I should (?:focus|mention|say)|my (?:response|argument) must|"
    r"perhaps I (?:should|can)|possible argument:)\b", re.IGNORECASE,
)


def _looks_like_leaked_reasoning(text: str) -> bool:
    """Heuristic safety net, not a formal parser: a real argument is short and states a
    position; leaked chain-of-thought is long and narrates the task/instructions back."""
    if len(text) > 700:
        return True
    return bool(_REASONING_LEAK_PATTERNS.search(text))


def advocate_config() -> tuple[str, str]:
    return os.environ.get("OPENROUTER_ADVOCATE_API_KEY", ""), \
        os.environ.get("OPENROUTER_ADVOCATE_MODEL", "qwen/qwen3.8-27b:free")


def challenger_config() -> tuple[str, str]:
    return os.environ.get("OPENROUTER_CHALLENGER_API_KEY", ""), \
        os.environ.get("OPENROUTER_CHALLENGER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
