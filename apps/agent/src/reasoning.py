"""Reasoning module — single Claude call per account_context, schema-validated.

Public entry: ``async score_account(context) -> Signal``.

Behaviour:
- Calls anthropic SDK with model from settings, system prompt from prompts/.
- The user message embeds the AccountContext as JSON + the schema instruction.
- Response is parsed as JSON, validated against Signal (Pydantic).
- Tenacity backoff on 429 / 5xx.
- On Pydantic ValidationError: retry once with the validation error appended to
  the user message. On second failure return is_signal=False with reason="validation_error".
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import get_settings
from prompts.expansion_reasoning import SCHEMA_INSTRUCTION, SYSTEM_PROMPT
from schemas.account_context import AccountContext
from schemas.signal import ModelMetadata, Signal

logger = logging.getLogger(__name__)


# --- transient-error class detection (used by tenacity predicate) ----------


def _is_transient(exc: BaseException) -> bool:
    """anthropic errors that should be retried."""
    # Import lazily so test collection doesn't require the SDK.
    try:
        import anthropic  # type: ignore

        transient = (
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.APIStatusError,
            anthropic.APITimeoutError,
        )
        return isinstance(exc, transient)
    except Exception:
        return False


# --- single Claude call ----------------------------------------------------


@retry(
    retry=retry_if_exception_type(Exception) & retry_if_exception_type(BaseException),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    reraise=True,
)
async def _call_anthropic(system: str, user: str, model: str, api_key: str) -> tuple[str, int, int]:
    """Returns (raw_text, tokens_in, tokens_out). Retries transient errors."""
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key)
    msg = await client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
    tokens_in = getattr(msg.usage, "input_tokens", 0) or 0
    tokens_out = getattr(msg.usage, "output_tokens", 0) or 0
    return text, tokens_in, tokens_out


@retry(
    retry=retry_if_exception_type(Exception) & retry_if_exception_type(BaseException),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    reraise=True,
)
async def _call_openai(system: str, user: str, model: str, api_key: str) -> tuple[str, int, int]:
    """OpenAI counterpart of _call_anthropic. Uses JSON mode (`response_format`)."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    msg = await client.chat.completions.create(
        model=model,
        max_tokens=4096,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    text = msg.choices[0].message.content or ""
    usage = getattr(msg, "usage", None)
    tokens_in = getattr(usage, "prompt_tokens", 0) or 0
    tokens_out = getattr(usage, "completion_tokens", 0) or 0
    return text, tokens_in, tokens_out


async def _call_claude(system: str, user: str, model: str, api_key: str) -> tuple[str, int, int]:
    """Provider-agnostic dispatch. Kept named ``_call_claude`` so existing tests
    that monkeypatch this attribute continue to work."""
    from config.settings import get_settings

    settings = get_settings()
    if settings.llm_provider == "openai":
        return await _call_openai(system, user, model, settings.openai_api_key)
    return await _call_anthropic(system, user, model, settings.anthropic_api_key)


# --- JSON extraction -------------------------------------------------------


def _extract_json(raw: str) -> dict:
    """Strict JSON; if the model wrapped in ```json fences, strip them."""
    s = raw.strip()
    if s.startswith("```"):
        # remove first fence line and trailing ```
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -3]
        s = s.strip()
    # Locate the first { and last } if there's stray prose.
    if not s.startswith("{"):
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1 and end > start:
            s = s[start : end + 1]
    return json.loads(s)


# --- main entry point ------------------------------------------------------


def _build_user_message(context: AccountContext, retry_hint: Optional[str] = None) -> str:
    parts = [
        SCHEMA_INSTRUCTION,
        "ACCOUNT CONTEXT (JSON):",
        context.model_dump_json(indent=2),
    ]
    if retry_hint:
        parts += [
            "PREVIOUS ATTEMPT FAILED VALIDATION:",
            retry_hint,
            "Return a corrected JSON object matching the schema exactly.",
        ]
    return "\n\n".join(parts)


def _ensure_ownership_present(payload: dict, context: AccountContext) -> dict:
    """If the model omitted ownership, fill from context (we know it)."""
    if payload.get("is_signal") and not payload.get("ownership"):
        payload["ownership"] = {
            "ae": {
                "name": context.ownership.ae.name,
                "role": context.ownership.ae.role,
            },
            "csm": {"name": context.ownership.csm.name},
        }
    return payload


async def score_account(
    context: AccountContext, *, model: Optional[str] = None
) -> Signal:
    """Score one account. Always returns a valid Signal (validation-failed → is_signal=False)."""
    settings = get_settings()
    chosen_model = model or settings.model

    if settings.llm_provider == "anthropic" and not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set; cannot call Claude. "
            "Use dry-run, set the key in .env, or switch LLM_PROVIDER=openai."
        )
    if settings.llm_provider == "openai" and not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY not set; cannot call OpenAI. "
            "Use dry-run or set the key in .env."
        )

    # api_key arg below is kept for interface compatibility — _call_claude
    # routes by provider and ignores it.
    api_key = settings.openai_api_key if settings.llm_provider == "openai" else settings.anthropic_api_key

    start = time.perf_counter()
    user_msg = _build_user_message(context)

    # First attempt
    raw, tin, tout = await _call_claude(
        SYSTEM_PROMPT, user_msg, chosen_model, api_key
    )
    try:
        payload = _ensure_ownership_present(_extract_json(raw), context)
        # Guarantee account_id/name match the context (model sometimes paraphrases).
        payload["account_id"] = context.account_id
        payload["account_name"] = context.account_name
        sig = Signal.model_validate(payload)
        sig.model_metadata = ModelMetadata(
            model=chosen_model,
            tokens_in=tin,
            tokens_out=tout,
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
        return sig
    except (ValidationError, json.JSONDecodeError, ValueError) as e:
        logger.warning("Signal validation failed for %s; retrying. error=%s", context.account_id, e)
        retry_user = _build_user_message(context, retry_hint=str(e))
        raw2, tin2, tout2 = await _call_claude(
            SYSTEM_PROMPT, retry_user, chosen_model, api_key
        )
        try:
            payload = _ensure_ownership_present(_extract_json(raw2), context)
            payload["account_id"] = context.account_id
            payload["account_name"] = context.account_name
            sig = Signal.model_validate(payload)
            sig.model_metadata = ModelMetadata(
                model=chosen_model,
                tokens_in=tin + tin2,
                tokens_out=tout + tout2,
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
            return sig
        except (ValidationError, json.JSONDecodeError, ValueError) as e2:
            logger.error(
                "Signal validation failed twice for %s; returning is_signal=False. error=%s",
                context.account_id,
                e2,
            )
            return Signal(
                account_id=context.account_id,
                account_name=context.account_name,
                is_signal=False,
                reasoning_trace=f"validation_error: {e2}",
                model_metadata=ModelMetadata(
                    model=chosen_model,
                    tokens_in=tin + tin2,
                    tokens_out=tout + tout2,
                    latency_ms=int((time.perf_counter() - start) * 1000),
                ),
            )
