"""LLM provider registry: OpenAI, Google Gemini, and Meta (Llama).

WHY MORE THAN ONE PROVIDER. A single `AQUA_AI_API_KEY` means the assistant is
exactly as available as one vendor's quota. This project is a student/portfolio
deployment where a free tier running out is a realistic and annoying failure, so
the assistant is built to fall through a list: if the configured provider fails
for an infrastructure reason, the next configured one is tried in the same turn.

WHAT THIS IS NOT. It is not load balancing or a "which model is best" router.
The order in `provider_order` is explicit configuration, and the fallback only
triggers on transport-level failure (missing key, timeout, rate limit, provider
error) — never on a refusal or a low-quality answer, because silently re-asking a
different model would make the assistant's behaviour unpredictable and untestable.

THE THREE PROVIDERS ARE NOT WIRED THE SAME WAY, and pretending otherwise would be
the classic bug in this kind of file:

  openai   POST {base}/chat/completions with `Authorization: Bearer`, native
           `tools` support. This is the canonical shape.
  gemini   Google's OpenAI-COMPATIBILITY endpoint
           (`generativelanguage.googleapis.com/v1beta/openai`). It accepts the
           same body, so it reuses the OpenAI path with a different base URL and
           key. That is a real endpoint, not a shim.
  meta     Llama models served through a Meta-hosted or third-party
           OpenAI-compatible endpoint (Groq, Together, Fireworks, a local vLLM).
           Meta does not publish a single first-party OpenAI-compatible
           chat-completions URL, so this provider REQUIRES an explicit base URL —
           see `resolve_providers`. Binding it to a guessed default would give a
           confusing "provider unavailable" on every call.
"""

from __future__ import annotations

from dataclasses import dataclass

PROVIDER_OPENAI = "openai"
PROVIDER_GEMINI = "gemini"
PROVIDER_META = "meta"

# Which base URLs and default models each provider starts from.
#
# `base_url` is None where the provider has no reliable default, so the resolver
# can report "not configured" instead of calling a URL that was invented here.
PROVIDER_DEFAULTS: dict[str, dict[str, str | None]] = {
    PROVIDER_OPENAI: {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        # The environment variable names read for this provider, most specific
        # first. The unprefixed AQUA_AI_* names are the project's originals.
        "keys": ("AQUA_AI_OPENAI_API_KEY", "AQUA_AI_API_KEY", "OPENAI_API_KEY"),
        "urls": ("AQUA_AI_OPENAI_BASE_URL", "AQUA_AI_BASE_URL", "OPENAI_BASE_URL"),
        "models": ("AQUA_AI_OPENAI_MODEL", "AQUA_AI_MODEL", "OPENAI_MODEL"),
    },
    PROVIDER_GEMINI: {
        # Google's OpenAI-compatibility layer. Confirmed public endpoint; it
        # speaks /chat/completions exactly like OpenAI.
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        # `gemini-3.5-flash-lite` rather than a numbered full model, and that is a
        # deliberate choice made after being burned twice:
        #
        #   * `gemini-2.0-flash` was hardcoded here and Google RETIRED it, so the
        #     provider answered 404 "no longer available to new users" on every
        #     request while the resolver still reported it as configured.
        #   * `gemini-3.5-flash` (the full model, not lite) was tried next and is
        #     over its free-tier quota on this key: 429 "exceeded your current
        #     quota", which reads identically to a transient rate limit and made
        #     the assistant report an outage.
        #
        # The LITE variant answers 200 with the full grounding prompt and all the
        # tool schemas, and carries its own, far larger free quota - so it keeps
        # answering when the full model's quota is spent. Verified live.
        "model": "gemini-3.5-flash-lite",
        "keys": ("AQUA_AI_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "urls": ("AQUA_AI_GEMINI_BASE_URL", "GEMINI_BASE_URL"),
        "models": ("AQUA_AI_GEMINI_MODEL", "GEMINI_MODEL"),
    },
    PROVIDER_META: {
        # No default BASE URL. Meta publishes Llama weights rather than one
        # hosted OpenAI-compatible endpoint, so the operator names the host they
        # use (Groq, Together, Fireworks, a local vLLM). Given one, this provider
        # behaves exactly like the others.
        "base_url": None,
        # A model is named here as a STARTING POINT, but it is only a default:
        # `AQUA_AI_META_MODEL` overrides it, and it will usually need to.
        #
        # This was `llama-3.3-70b-versatile`, which does not exist on a Groq
        # account (verified by listing the account's models: it offers gpt-oss
        # and qwen, no Llama). Renamed to a model that IS served there, because
        # the operator's key in this project is a Groq key - the `gsk_` prefix
        # says so - and a default that 404s is worse than no default.
        "model": "openai/gpt-oss-120b",
        "keys": ("AQUA_AI_META_API_KEY", "META_API_KEY", "GROQ_API_KEY", "TOGETHER_API_KEY"),
        "urls": ("AQUA_AI_META_BASE_URL", "META_BASE_URL", "GROQ_BASE_URL"),
        "models": ("AQUA_AI_META_MODEL", "META_MODEL"),
    },
}


@dataclass(frozen=True)
class ProviderConfig:
    """One resolved, callable provider."""

    name: str
    api_key: str
    model: str
    base_url: str
    timeout: int = 30

    @property
    def is_configured(self) -> bool:
        """A provider is usable only when it has BOTH a key and a URL."""
        return bool(self.api_key and self.model and self.base_url)


def _first_set(value_map: dict[str, str], names: tuple[str, ...]) -> str:
    """Return the first non-blank value among `names`, or an empty string.

    BOTH NAMESPACES ARE CHECKED, and that is the whole point of this helper.

    The names in PROVIDER_DEFAULTS are ENVIRONMENT VARIABLE names
    (AQUA_AI_GEMINI_API_KEY), because that is what an operator writes in .env.
    But this function is handed current_app.config, which only contains the
    canonical keys config.py explicitly read (AI_API_KEY, AI_BASE_URL, ...).

    Looking up only the env names therefore found NOTHING, and every provider
    was reported unconfigured while the keys sat in .env perfectly valid. The
    assistant answered "no provider is configured" with two working keys
    installed, which is the most confusing possible failure.

    So each name is tried as given, then with the AQUA_AI_ prefix stripped so
    it also matches the Flask config key.
    """
    for name in names:
        candidate = (value_map.get(name) or "").strip()
        if candidate:
            return candidate
        # AQUA_AI_GEMINI_API_KEY -> GEMINI_API_KEY, the form config.py stores.
        # AI_API_KEY has no prefix to strip and matches the first lookup.
        if name.startswith("AQUA_AI_"):
            stripped = name[len("AQUA_AI_") :]
            candidate = (value_map.get(stripped) or "").strip()
            if candidate:
                return candidate
    return ""


def resolve_providers(config: dict) -> list[ProviderConfig]:
    """Build the ordered list of configured providers.

    Order comes from `AQUA_AI_PROVIDER_ORDER` (comma-separated), falling back to
    the single `AQUA_AI_PROVIDER` value that older deployments already set. Both
    are honoured so an existing `.env` keeps working unchanged.

    Providers with no credentials are skipped rather than returned with empty
    fields: the caller then has a list it can actually iterate, and "nothing is
    configured" is a single `len(...) == 0` check instead of a per-provider one.
    """
    # Both spellings are accepted: `AI_PROVIDER_ORDER` is the Flask config key
    # (what `current_app.config` exposes), and `AQUA_AI_PROVIDER_ORDER` is the
    # environment variable an operator actually sets. Callers pass one or the
    # other depending on where they are, and a resolver that understood only one
    # would silently ignore the setting half the time.
    order_raw = _first_set(
        config, ("AI_PROVIDER_ORDER", "AQUA_AI_PROVIDER_ORDER", "AI_PROVIDER_ORDER_ALT")
    )
    if order_raw:
        requested = [part.strip().lower() for part in order_raw.split(",") if part.strip()]
    else:
        single = (
            _first_set(config, ("AI_PROVIDER", "AQUA_AI_PROVIDER")) or PROVIDER_OPENAI
        ).strip().lower()
        requested = [single]

    timeout = int(config.get("AI_REQUEST_TIMEOUT", 30) or 30)

    resolved: list[ProviderConfig] = []
    seen: set[str] = set()

    for name in requested:
        if name in seen:
            continue
        seen.add(name)

        defaults = PROVIDER_DEFAULTS.get(name)
        if defaults is None:
            # An unknown name is skipped rather than raising: a typo in the order
            # string should not take the assistant down when another provider in
            # the same list is perfectly usable.
            continue

        api_key = _first_set(config, defaults["keys"])
        base_url = _first_set(config, defaults["urls"]) or (defaults["base_url"] or "")
        model = _first_set(config, defaults["models"]) or (defaults["model"] or "")

        candidate = ProviderConfig(
            name=name,
            api_key=api_key,
            model=model,
            base_url=str(base_url).rstrip("/"),
            timeout=timeout,
        )
        if candidate.is_configured:
            resolved.append(candidate)

    return resolved


def describe_providers(config: dict) -> dict:
    """Report which providers are configured, WITHOUT exposing any secret.

    Used by the admin diagnostics view and by `/ai/tools`-style introspection.
    It reports whether a key is present, never the key, and never a prefix of it
    — a partial key in a log or an API response is still a leaked credential.
    """
    configured = {p.name: p for p in resolve_providers(config)}

    return {
        "order": [p.name for p in resolve_providers(config)],
        "active": next(iter(configured), None),
        "providers": [
            {
                "name": name,
                "configured": name in configured,
                "model": configured[name].model if name in configured else None,
                "base_url": configured[name].base_url if name in configured else None,
            }
            for name in PROVIDER_DEFAULTS
        ],
    }
