"""Shared model plumbing for Unjiggle's AI features.

Every AI feature (layout analysis, the AI Stylist, the Personality Mirror and the
App Obituary) asks the model for one JSON object that matches a JSON schema:

- Claude: structured outputs (``output_config.format``). The API guarantees a
  schema-valid reply, so there is no tool call to force: Claude Opus 5.5 rejects
  ``tool_choice`` of type ``tool`` or ``any`` with a 400.
- OpenAI: a forced function call whose parameters are the same schema.

This module owns provider routing, the default models and the Claude request, so
the features stay consistent with each other.
"""

from __future__ import annotations

import importlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

# Layout analysis and the AI Stylist plan changes to the phone, so they use the
# strongest model by default.
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"
# The Personality Mirror and the App Obituary only write short text about the phone.
# Claude Sonnet 5 writes it well and answers sooner.
DEFAULT_ANTHROPIC_WRITING_MODEL = "claude-sonnet-5"
DEFAULT_OPENAI_MODEL = "gpt-4.1"

# Claude Opus 5.5 always thinks, and thinking counts toward max_tokens, so the
# ceiling has to cover the thinking as well as the JSON reply. 16K is the
# non-streaming ceiling that stays within the SDK's HTTP timeout. How much the
# model thinks is controlled by each feature's effort level, not by this number.
CLAUDE_MAX_TOKENS = 16000

# Server-side refusal fallbacks: when a safety classifier declines a request, the
# API re-runs it on the model Anthropic recommends for that refusal category.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Models without structured outputs, which every AI feature relies on: the Claude 3
# family and the first Claude 4 models (Sonnet 4 and Opus 4, dated 2025-05-14).
# They are refused before any request is sent.
_NO_STRUCTURED_OUTPUT_PREFIXES = (
    "claude-3",
    "claude-4-",
    "claude-sonnet-4-0",
    "claude-sonnet-4-2",
    "claude-opus-4-0",
    "claude-opus-4-2",
)

# Supported models that reject output_config.effort. Newer models all accept it.
_NO_EFFORT_PREFIXES = (
    "claude-haiku-4",
    "claude-sonnet-4-5",
    "claude-opus-4-1",
)

# Models whose safety classifiers can decline a request and that accept
# server-side fallbacks.
_FALLBACK_PREFIXES = ("claude-opus-5", "claude-fable-5", "claude-mythos-5")

_OPENAI_MODEL_RE = re.compile(r"^(gpt-|chatgpt-|o\d)")


class LLMError(RuntimeError):
    """The model answered, but not with a usable result."""


class LLMRefusalError(LLMError):
    """A safety classifier or the model declined the request (stop_reason "refusal")."""

    def __init__(self, category: str | None = None):
        self.category = category
        detail = f" (category: {category})" if category else ""
        super().__init__(f"Claude declined this request{detail}.")


class LLMTruncatedError(LLMError):
    """The reply hit max_tokens before the JSON was complete."""

    def __init__(self) -> None:
        super().__init__("Claude's reply was cut off before it finished (max_tokens).")


class LLMOutputError(LLMError):
    """The reply had no JSON object where one was expected."""


class LLMUnsupportedModelError(LLMError):
    """The requested model can't return structured output, so no request is sent."""

    def __init__(self, model: str) -> None:
        self.model = model
        super().__init__(
            f"{model} does not support structured outputs, which Unjiggle's AI features "
            f"need. Use the default ({DEFAULT_ANTHROPIC_MODEL}), or Claude Haiku 4.5, "
            "Sonnet 4.5, Opus 4.5 or a newer model."
        )


def resolve_provider(
    api_key: str | None, model: str | None = None, provider: str = "auto",
) -> str:
    """Pick "anthropic" or "openai" for a request.

    An explicit provider wins. Otherwise the model name decides (``claude-*`` is
    Anthropic; ``gpt-*`` and the o-series are OpenAI), and failing that the key's
    prefix: Anthropic keys start with ``sk-ant-``, OpenAI keys with ``sk-``
    (``sk-proj-`` included). Anything else goes to Anthropic.
    """
    if provider in ("anthropic", "openai"):
        return provider
    if provider != "auto":
        raise ValueError(f"Unknown provider {provider!r}: use 'anthropic', 'openai' or 'auto'.")
    if model:
        if model.startswith("claude-"):
            return "anthropic"
        if _OPENAI_MODEL_RE.match(model):
            return "openai"
    if api_key and api_key.startswith("sk-") and not api_key.startswith("sk-ant-"):
        return "openai"
    return "anthropic"


def resolve_api_key(provider: str, api_key: str | None) -> str | None:
    """Return a key that belongs to ``provider``.

    The CLI reads ANTHROPIC_API_KEY before OPENAI_API_KEY, so when both are set the
    key it passes can belong to the other provider (for example with
    ``--model gpt-4.1``). In that case, use the provider's own environment variable.
    """
    if not api_key:
        return api_key
    is_anthropic_key = api_key.startswith("sk-ant-")
    if provider == "openai" and is_anthropic_key:
        return os.environ.get("OPENAI_API_KEY") or api_key
    if provider == "anthropic" and not is_anthropic_key and api_key.startswith("sk-"):
        return os.environ.get("ANTHROPIC_API_KEY") or api_key
    return api_key


def resolve_route(
    api_key: str | None,
    model: str | None = None,
    provider: str = "auto",
    anthropic_default: str = DEFAULT_ANTHROPIC_MODEL,
) -> tuple[str, str | None, str]:
    """Return ``(provider, api_key, model)`` for one AI request, filling in defaults.

    ``anthropic_default`` is the feature's Claude model when no model is given.
    """
    provider = resolve_provider(api_key, model, provider)
    api_key = resolve_api_key(provider, api_key)
    if not model:
        model = anthropic_default if provider == "anthropic" else DEFAULT_OPENAI_MODEL
    return provider, api_key, model


def supports_structured_outputs(model: str) -> bool:
    return not model.startswith(_NO_STRUCTURED_OUTPUT_PREFIXES)


def supports_effort(model: str) -> bool:
    return not model.startswith(_NO_EFFORT_PREFIXES)


def supports_fallbacks(model: str) -> bool:
    return model.startswith(_FALLBACK_PREFIXES)


def today_line() -> str:
    """First line of every layout context. Staleness judgments need a 'now'."""
    return f"TODAY: {datetime.now().astimezone().date().isoformat()}"


# Layout contexts show an app's update year only when the app has had no App Store
# update for about 18 months. A full timestamp for every app uses many tokens and
# adds nothing to a staleness judgment.
STALE_DAYS = 548


def stale_year(meta: dict | None, now: datetime) -> int | None:
    """Year of the app's last App Store update, if it is STALE_DAYS old or more."""
    raw = (meta or {}).get("last_updated")
    if not raw:
        return None
    try:
        when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.year if (now - when).days >= STALE_DAYS else None


def provider_api_errors() -> tuple[type[Exception], ...]:
    """Base API error classes of the installed provider SDKs.

    These cover failures before any answer arrives: authentication, no access to
    the model, rate limits, overload and network errors. Callers that treat AI as
    optional catch them next to LLMError.
    """
    errors: list[type[Exception]] = []
    for name in ("anthropic", "openai"):
        try:
            module = importlib.import_module(name)
        except ImportError:
            continue
        error = getattr(module, "APIError", None)
        if isinstance(error, type) and issubclass(error, Exception):
            errors.append(error)
    return tuple(errors)


def _require_anthropic():
    try:
        import anthropic
    except ImportError as exc:
        raise ImportError(
            "AI features need the anthropic package: pip install 'unjiggle[ai]'"
        ) from exc
    return anthropic


def _anthropic_client(api_key: str | None):
    return _require_anthropic().Anthropic(api_key=api_key)


def claude_json(
    *,
    api_key: str | None,
    model: str,
    system: str,
    user: str,
    schema: dict[str, Any],
    effort: str,
    cached_prefix: str | None = None,
) -> dict[str, Any]:
    """Ask Claude for one JSON object matching ``schema`` and return it.

    Thinking is left at its default (adaptive; always on for Claude Opus 5.5) and
    ``effort`` sets how much of it happens. Raises LLMUnsupportedModelError before
    any request for a model without structured outputs, and LLMRefusalError,
    LLMTruncatedError or LLMOutputError when the reply is not usable; SDK errors
    (authentication, rate limits, overload) propagate unchanged.

    ``cached_prefix`` is text that goes before ``user`` in the same message and is
    the same for the next few requests, such as a phone's layout. The system prompt
    and the prefix then get cache breakpoints, so a request that repeats them within
    a few minutes reads them from the prompt cache.
    """
    if not supports_structured_outputs(model):
        raise LLMUnsupportedModelError(model)
    client = _anthropic_client(api_key)
    output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
    if supports_effort(model):
        output_config["effort"] = effort
    system_param: Any = system
    content: Any = user
    if cached_prefix is not None:
        breakpoint_ = {"type": "ephemeral"}
        system_param = [{"type": "text", "text": system, "cache_control": breakpoint_}]
        content = [
            {"type": "text", "text": cached_prefix, "cache_control": breakpoint_},
            {"type": "text", "text": user},
        ]
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": CLAUDE_MAX_TOKENS,
        "system": system_param,
        "messages": [{"role": "user", "content": content}],
        "output_config": output_config,
    }
    if supports_fallbacks(model):
        response = client.beta.messages.create(
            **params, betas=[FALLBACK_BETA], fallbacks="default",
        )
    else:
        response = client.messages.create(**params)
    return parse_json_reply(response)


def parse_json_reply(response) -> dict[str, Any]:
    """Check why Claude stopped, then read the JSON from the first text block.

    The reply can start with thinking blocks (and, after a refusal fallback, a
    fallback marker), so blocks are selected by type, never by position.
    """
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        raise LLMRefusalError(getattr(details, "category", None))
    if response.stop_reason == "max_tokens":
        raise LLMTruncatedError()
    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        raise LLMOutputError("Claude returned no JSON result.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMOutputError("Claude returned malformed JSON.") from exc
    if not isinstance(data, dict):
        raise LLMOutputError("Claude returned JSON that is not an object.")
    return data
