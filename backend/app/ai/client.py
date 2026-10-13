"""Provider-agnostic LLM transport.

Any service that speaks the OpenAI chat-completions schema works here (OpenAI,
Azure OpenAI, Groq, Together, a local Ollama/vLLM endpoint) by pointing
`AQUA_AI_BASE_URL` at it. The client is intentionally thin — prompt construction and
tool parsing live in their own modules.

When `AI_ENABLED` is false or no key is configured, `is_configured()` returns
False and callers must surface that state to the user rather than fabricating a
reply. No mock responses are generated anywhere in this codebase.

Configuration comes ONLY from the backend environment:

    AQUA_AI_API_KEY   the provider key (never leaves this process)
    AQUA_AI_MODEL     the model identifier

The key is read here and nowhere else. It is never returned in a response, never
logged, and never serialised into an error message. There is deliberately no
VITE_-prefixed variable for it, because anything VITE_-prefixed is compiled
into the browser bundle and is therefore public. React talks to Flask; Flask
talks to the provider.
"""

import logging
from typing import Any

import requests
from flask import current_app

logger = logging.getLogger(__name__)

# Distinguishes "the provider rejected the request because we are out of quota"
# from every other transport failure, so the service can answer with a 429-shaped
# message instead of a generic 502.
RATE_LIMIT_STATUS = 429
# The provider refused the request for being larger than its per-minute token
# budget (Groq returns this as 413 "Request too large"). Distinguished from a
# generic provider error so the client can shed the tool schemas and retry.
PAYLOAD_TOO_LARGE_STATUS = 413


def _is_token_budget_429(response) -> bool:
    """True when a 429 is a TOKEN-per-minute budget rejection, not a request rate.

    Providers overload 429 for two very different conditions, and treating them
    the same is what made the assistant report a permanent outage for a problem
    that clearing the tool schemas solves:

      * REQUESTS per minute - too many calls. Waiting is the only fix; retrying
        immediately would just burn more of the allowance. Stays a rate limit.
      * TOKENS per minute - the request itself is larger than the minute's token
        budget (Groq free tier: 8000). A smaller request, here one without the
        tool schemas, can succeed within the same minute. This is the case worth
        retrying.

    Detected from the response body rather than a header, because the body is
    what actually names the cause: Groq writes `"type":"tokens"` and the phrase
    "on tokens per minute (TPM)". The body is READ but never LOGGED - it can echo
    request headers, and those carry the key. Only the two boolean signals are
    extracted here.

    Falls back to False when the body cannot be parsed, so an unreadable 429 is
    treated as an ordinary rate limit (retry the request later) rather than
    silently shed as a size problem.
    """
    try:
        body = response.json()
    except (ValueError, TypeError):
        return False

    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return False

    # Groq's machine-readable marker for a token-budget rejection.
    if str(error.get("type") or "").lower() == "tokens":
        return True

    # Free-text fallback for other OpenAI-compatible providers that describe the
    # same condition without a stable `type`. Matched case-insensitively.
    message = str(error.get("message") or "").lower()
    return "tokens per minute" in message or "token limit" in message


class LLMError(Exception):
    """Transport-level failure talking to the LLM provider.

    Carries a `kind` so the service layer can map it onto the right user-facing
    status without re-inspecting the HTTP response:

        "missing_key"   no provider configured
        "timeout"       the provider did not answer in time
        "rate_limit"    quota/rate limit exceeded
        "provider"      the provider returned a non-2xx status
        "malformed"     the provider returned a body we cannot read
    """

    def __init__(self, kind: str, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status_code = status_code
class LLMClient:
    """Minimal OpenAI-compatible chat client."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "",
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key or ""
        self.model = model or ""
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.timeout = timeout

    def is_configured(self) -> bool:
        """True when the client has everything it needs to make a call."""
        return bool(self.api_key and self.model)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """Send a chat completion request.

        Returns the assistant message dict, which may contain either `content`
        (a normal reply) or `tool_calls` (a request to run an application tool).
        Raises `requests.RequestException` on transport failure so the service
        layer can map it to a 502.
        """
        if not self.is_configured():
            raise LLMError("missing_key", "No LLM provider is configured")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        # BOUND THE REPLY LENGTH, WHICH IS WHAT BOUNDS THE REPLY TIME.
        #
        # Generation time is proportional to the number of tokens the provider
        # writes, and a chat answer is expected to be short. Without a cap the
        # model is free to write a 600-token essay for "what is pH", which is the
        # difference between a ~2 second answer and a ~6 second one. Capping at a
        # chat-sized budget keeps a normal answer well inside the 2-3 second
        # target, and it is still generous enough for a list or an explanation.
        #
        # Read from config so a deployment can raise it without a code change;
        # the default suits short conversational replies.
        try:
            from flask import current_app

            max_tokens = int(current_app.config.get("AI_MAX_RESPONSE_TOKENS", 500))
        except (RuntimeError, ImportError, ValueError, TypeError):
            # Importable outside an app context (training scripts, tests).
            max_tokens = 500
        if max_tokens > 0:
            payload["max_tokens"] = max_tokens
        if tools:
            # Wrap each bare spec in the OpenAI function-tool envelope.
            #
            # `get_ai_tool_specs()` returns `{name, description, parameters}` -
            # the OUTER `{type: "function", function: {...}}` is not part of it.
            # Sending the bare form is rejected with a 400 by every real provider:
            # the request is well-formed JSON but the tool entries have no `name`
            # where the API looks for it (it is expected one level deeper).
            #
            # This went unnoticed because the whole existing test suite
            # monkeypatches the client, so no test ever built a real payload.
            # The error it caused was opaque - "The AI provider returned an
            # error" - and the body is deliberately not logged, so the cause was
            # invisible from the log as well.
            payload["tools"] = [
                {"type": "function", "function": spec} for spec in tools
            ]
            payload["tool_choice"] = "auto"

        try:
            response = self._post(payload)

            # A 413 - OR a 429 that names the TOKEN budget - is a SIZE problem,
            # not a transient outage: the provider meters tokens per minute and
            # this request is over it. The tool schemas are the most compressible
            # part of a chat turn, so drop them and retry ONCE before giving up.
            # Every question that does not need the user's own data (definitions,
            # how the model works, general water science) is answerable without
            # tools, so this turns a hard failure into a working reply for the
            # common case.
            #
            # WHY 429 IS INCLUDED, AND WHY IT IS THE IMPORTANT ONE. Groq's
            # on-demand tier caps at 8000 tokens per minute and, once any of that
            # budget has been spent, it rejects the NEXT request with 429 rather
            # than 413: the body says "Rate limit reached ... on tokens per minute
            # (TPM): Limit 8000". Only 413 was retried here, so this exact case -
            # a full grounding prompt plus the tool schemas landing on a partially
            # spent minute - was reported to the user as "the AI provider is
            # unavailable" even though dropping the tools would have answered.
            #
            # A genuine REQUESTS-per-minute 429 is left alone: the body does not
            # name tokens, `_is_token_budget_429` returns False, and it stays a
            # rate limit so the client backs off rather than silently shedding
            # tools. See that helper for the distinction.
            is_size_reject = response.status_code == PAYLOAD_TOO_LARGE_STATUS or (
                response.status_code == RATE_LIMIT_STATUS
                and _is_token_budget_429(response)
            )
            if is_size_reject and "tools" in payload:
                logger.warning(
                    "Aqua AI provider rejected the payload as too large "
                    "(HTTP %s); retrying without tool schemas",
                    response.status_code,
                )
                trimmed = {k: v for k, v in payload.items() if k not in ("tools", "tool_choice")}
                response = self._post(trimmed)
        except requests.Timeout as exc:
            logger.warning("Aqua AI provider timed out after %ss", self.timeout)
            raise LLMError("timeout", "The AI provider timed out") from exc
        except requests.RequestException as exc:
            # Connection refused, DNS failure, TLS error, etc. Only the exception
            # type is logged — provider text can echo request headers back.
            logger.warning("Aqua AI provider request failed: %s", type(exc).__name__)
            raise LLMError("provider", "The AI provider is unavailable") from exc
        if response.status_code == RATE_LIMIT_STATUS:
            # A 429 that names the TOKEN budget, surviving the tools-off retry
            # above, is still a SIZE problem: the baseline system prompt alone is
            # over the provider's per-minute allowance right now. Reported with
            # the `too_large` kind ("try again in a moment") rather than the
            # generic rate limit, so the service can back off by waiting instead
            # of rolling through every provider and reporting an outage.
            if _is_token_budget_429(response):
                logger.warning("Aqua AI provider token budget exhausted")
                raise LLMError(
                    "too_large",
                    "The request is larger than the AI provider allows right now. "
                    "Try a shorter question, or try again shortly.",
                    status_code=RATE_LIMIT_STATUS,
                )
            logger.warning("Aqua AI provider rate limit reached")
            raise LLMError(
                "rate_limit",
                "The AI provider is rate limiting requests. Try again shortly.",
                status_code=RATE_LIMIT_STATUS,
            )

        if not response.ok:
            # Status code only; deliberately NOT the body, which can echo request
            # headers back and would risk writing the key into the log.
            logger.warning("Aqua AI provider returned HTTP %s", response.status_code)
            # A 413 that survived the tools-off retry is still a size problem,
            # not a generic provider failure, so it keeps its own kind and reads
            # correctly in the log and the client message.
            if response.status_code == PAYLOAD_TOO_LARGE_STATUS:
                raise LLMError(
                    "too_large",
                    "The request is larger than the AI provider allows right now. "
                    "Try a shorter question, or try again shortly.",
                    status_code=response.status_code,
                )
            raise LLMError(
                "provider",
                "The AI provider returned an error",
                status_code=response.status_code,
            )

        try:
            body = response.json()
            content = body["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            logger.warning("Aqua AI provider returned a malformed response")
            raise LLMError(
                "malformed", "The AI provider returned an unreadable response"
            ) from exc
        if not isinstance(content, dict):
            raise LLMError("malformed", "The AI provider returned an unreadable response")

        return content

    def _post(self, payload: dict[str, Any]):
        """POST one chat-completions payload and return the raw response.

        Extracted so the size-retry in `chat` can send a second, trimmed payload
        without duplicating the headers and timeout. Transport exceptions are left
        to propagate: `chat` maps them onto `LLMError` in one place.
        """
        return requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )


def get_llm_client() -> LLMClient:
    """Build an `LLMClient` from the active application configuration.

    Reads the canonical `AQUA_AI_*` variables only. The key stays inside the
    process: it is placed on the outgoing Authorization header and nowhere else.
    """
    from app.ai.providers import resolve_providers
    providers = resolve_providers(current_app.config)
    if not providers:
        # No provider has both a key and a URL. Return an unconfigured client so
        # `is_configured()` reports that honestly, rather than the caller meeting
        # a TypeError on a missing provider.
        return LLMClient(api_key="", model="")

    first = providers[0]
    return LLMClient(
        api_key=first.api_key,
        model=first.model,
        base_url=first.base_url,
        timeout=first.timeout,
    )


def call_with_fallback(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.3,
) -> tuple[dict[str, Any], str]:
    """Send a turn, trying each configured provider in order.

    Returns `(assistant_message, provider_name)`.

    WHAT TRIGGERS A FALLBACK. Only infrastructure failure — a missing key, a
    timeout, a rate limit, a provider error or an unreadable body. A provider
    that ANSWERS, even unhelpfully, has answered: silently re-asking a different
    model would make the assistant's replies depend on which vendor happened to
    be reachable, which is neither explainable to the user nor reproducible in a
    test.

    Every failure is collected, so when they all fail the caller gets one message
    naming what actually went wrong rather than a generic "the AI is
    unavailable".
    """
    from app.ai.providers import resolve_providers
    providers = resolve_providers(current_app.config)
    if not providers:
        raise LLMError("missing_key", "No LLM provider is configured")

    failures: list[str] = []

    for provider in providers:
        client = LLMClient(
            api_key=provider.api_key,
            model=provider.model,
            base_url=provider.base_url,
            timeout=provider.timeout,
        )
        try:
            message = client.chat(messages, tools=tools, temperature=temperature)
            if failures:
                logger.info(
                    "Aqua AI answered via %s after %s earlier failure(s)",
                    provider.name,
                    len(failures),
                )
            return message, provider.name
        except LLMError as exc:
            # Only the KIND is logged. The provider's own message can echo request
            # headers back, and those carry the key.
            logger.warning(
                "Aqua AI provider %s failed (%s); trying the next one",
                provider.name,
                exc.kind,
            )
            failures.append(f"{provider.name}: {exc.kind}")

    # Every provider failed. The last kind is the most useful signal — a rate
    # limit is worth retrying, a bad key is not — so it is what the caller sees,
    # with the full roll-call attached as context.
    raise LLMError(
        "provider",
        "All configured AI providers failed (" + ", ".join(failures) + ")",
    )
