"""Aqua AI service - conversation orchestration and memory.

A conversation is a persisted, user-owned thread:

    aqua_ai_conversations   one row per thread, owned by `user_id`
    aqua_ai_messages        one row per turn, ordered by id
Every turn is stored, and the whole thread is the assistant's memory. When a
follow-up arrives ("why is it important?", "what does that mean?"), the prior
turns are replayed to the model as ordinary chat messages, so the pronoun has
something to bind to. Only a bounded recent window is sent, trimmed to start on
a user turn.

Ownership is enforced here, not merely in the route: a conversation id that
belongs to another account is treated as absent (404), so one user can never
read, extend or delete another's thread.
"""

import json
import logging
import time
from typing import Any
from flask import current_app

from app.ai.client import LLMError, get_llm_client, LLMClient
from app.ai.providers import resolve_providers
from app.ai.prompts import build_conversation_context
# The unpatched factory, captured at import time. `_get_client` compares against
# this to tell "the tests replaced the factory" from "nobody touched it".
_ORIGINAL_GET_LLM_CLIENT = get_llm_client
class _FallbackClient:
    """A client facade that tries each configured provider in order.

    WHY A FACADE RATHER THAN CALLING `call_with_fallback` DIRECTLY. The turn loop
    in this service calls `client.chat(...)` several times in one request, and it
    has to keep calling the SAME object so the tests can substitute a fake with
    `monkeypatch.setattr(svc, "get_llm_client", ...)`. Changing the call sites to
    a module-level function would have broken every one of those tests, so the
    fallback lives behind the same interface instead.

    `is_configured()` reports True when ANY provider is usable, which is what
    makes "no provider configured" a single honest check rather than a loop that
    discovers it one call at a time.
    """

    def __init__(self, providers) -> None:
        self._providers = providers
    def is_configured(self) -> bool:
        return bool(self._providers)

    def chat(self, messages, tools=None, temperature: float = 0.3):
        failures: list[str] = []

        for provider in self._providers:
            client = LLMClient(
                api_key=provider.api_key,
                model=provider.model,
                base_url=provider.base_url,
                timeout=provider.timeout,
            )
            try:
                return client.chat(messages, tools=tools, temperature=temperature)
            except LLMError as exc:
                # The provider's own message is never logged: it can echo request
                # headers, and those carry the key.
                logger.warning(
                    "Aqua AI provider %s failed (%s); trying the next one",
                    provider.name,
                    exc.kind,
                )
                failures.append(f"{provider.name}: {exc.kind}")

        # Every provider failed. Which kind is surfaced matters, because the
        # service maps it to a different user-facing status. A turn where EVERY
        # provider was merely at its token/rate limit is really "try again in a
        # moment", not "the AI is unavailable" - the latter reads as a permanent
        # outage and sends the user away for no reason. So when every failure is
        # a size or rate condition, that is what is re-raised.
        kinds = [entry.split(": ", 1)[-1] for entry in failures]
        if kinds and all(kind in ("too_large", "rate_limit") for kind in kinds):
            raise LLMError(
                "rate_limit",
                "All configured AI providers are at their rate limit ("
                + ", ".join(failures)
                + ")",
            )
        raise LLMError(
            "provider",
            "All configured AI providers failed (" + ", ".join(failures) + ")",
        )


def _get_client():
    """Return the client the turn loop should use.

    Two requirements pull against each other and both must hold:

      1. Production must try EVERY configured provider, so a rate limit or outage
         on the first one falls through to the next (that is `_FallbackClient`).
      2. The tests inject a fake with `monkeypatch.setattr(svc, "get_llm_client",
         ...)`, and that fake must be the client that actually runs.

    A replaced factory wins outright (requirement 2). An untouched one falls back
    to the provider list: two or more providers get the facade (requirement 1).
    """
    # A monkeypatched factory is honoured verbatim: the tests inject a fake here,
    # and it must be the client that actually runs. Identity comparison is the
    # signal, because the replacement can be any callable, not just a fake class.
    if get_llm_client is not _ORIGINAL_GET_LLM_CLIENT:
        return get_llm_client()

    # Production path. With more than one provider configured, use the facade so a
    # rate limit or outage on the first provider falls through to the next rather
    # than failing the whole turn.
    providers = resolve_providers(current_app.config)
    if len(providers) > 1:
        return _FallbackClient(providers)
    return get_llm_client()
from app.ai.safety import classify_intent, redact_secrets, refusal_for
from app.ai.tool_runner import execute_tool
from app.constants import (
    AI_MESSAGE_STATUS_ERROR,
    AI_MESSAGE_STATUS_OK,
    AI_ROLE_ASSISTANT,
    AI_ROLE_USER,
)
from app.extensions import db
from app.models import AIConversation, AIMessage
from app.utils.ai_tools import (
    EXPLAIN_TOOL_NAME,
    NAVIGATION_LABELS,
    NAVIGATION_TARGETS,
    NAVIGATION_TOOL_FOR_TARGET,
    get_ai_tool_specs,
    get_navigation_target,
    resolve_explain_intent,
    resolve_navigation_intent,
)
from app.utils.errors import (
    AquaGuardError,
    ExternalServiceError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    UpstreamTimeoutError,
    ValidationError,
)
from app.utils.pagination import paginate_query

logger = logging.getLogger(__name__)

# How many times the model may call a tool before it must answer.
#
# LOWERED FROM 3 TO 2 FOR SPEED. Each round is a separate, SEQUENTIAL model call,
# and the time to answer is dominated by how many round-trips it takes. The
# assistant's normal turn needs exactly ONE call (fetch the user's data, then
# answer), so 2 is generous: it still allows a second tool to be consulted when
# the first genuinely could not answer, but it stops a model that wanders through
# three tool calls from turning a 2-second answer into a 6-second one. A turn that
# exhausts this loop is asked once more for plain text, so the user always gets an
# answer rather than an empty reply.
_MAX_TOOL_ROUNDS = 2


def _current_user_id() -> int:
    """The account this conversation belongs to.

    Delegates to the one shared rule in `app.services.identity`: a request with a
    valid token acts as that account, and anything else acts as the shared
    visitor. Threads stay owned and isolated exactly as before.
    """
    from app.services.identity import current_user_id

    return current_user_id()


def _serialize_conversation(conversation: AIConversation, include_messages: bool = False) -> dict[str, Any]:
    payload = conversation.to_dict()
    if include_messages:
        payload["messages"] = [
            message.to_dict()
            for message in conversation.messages.order_by(AIMessage.id).all()
        ]
    return payload


def _title_from(text: str) -> str:
    """Derive a short conversation title from the first user message."""
    cleaned = " ".join(text.split())
    return (cleaned[:77] + "...") if len(cleaned) > 80 else (cleaned or "New conversation")


def _assert_owns_conversation(user_id: int, conversation_id: int) -> AIConversation:
    """Return a conversation only if it belongs to `user_id`.

    Reported as NotFound (404) rather than Forbidden (403): a caller must not be
    able to probe which conversation ids exist by comparing "forbidden" against
    "not found". The single implementation is shared by the chat path and the
    read/delete paths so ownership is checked identically everywhere.
    """
    conversation = db.session.get(AIConversation, conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise NotFoundError("Conversation not found")
    return conversation

def _get_or_create_conversation(user_id: int, conversation_id: int | None) -> AIConversation:
    if conversation_id is None:
        conversation = AIConversation(user_id=user_id, title="New conversation")
        db.session.add(conversation)
        db.session.commit()
        _prune_conversations(user_id)
        return conversation

    return _assert_owns_conversation(user_id, conversation_id)


# The account keeps only its TEN most recent threads. The requirement is a
# rolling window rather than unbounded growth: on the eleventh new conversation
# the oldest is deleted (its messages go with it, via the model's cascade), so
# history never accumulates beyond ten per account.
_MAX_CONVERSATIONS_PER_USER = 10


def _prune_conversations(user_id: int) -> None:
    """Delete the caller's oldest conversations beyond the ten newest.

    Runs after a NEW thread is created, which is the only moment the count can
    exceed the window. Kept deliberately cheap: one query for the cutoff id,
    one delete. Pruning here (creation time) rather than on every turn keeps a
    normal chat turn free of any extra writes.
    """
    try:
        keep_ids = (
            db.session.execute(
                db.select(AIConversation.id)
                .where(AIConversation.user_id == user_id)
                .order_by(AIConversation.id.desc())
                .limit(_MAX_CONVERSATIONS_PER_USER)
            )
            .scalars()
            .all()
        )
        stale = (
            AIConversation.query.filter(AIConversation.user_id == user_id)
            .filter(~AIConversation.id.in_(keep_ids))
            .all()
            if len(keep_ids) >= _MAX_CONVERSATIONS_PER_USER
            else []
        )
        if stale:
            for old in stale:
                db.session.delete(old)
            db.session.commit()
            logger.info(
                "Pruned %d old Aqua AI conversations for user=%s (kept %d)",
                len(stale),
                user_id,
                len(keep_ids),
            )
    except Exception:  # noqa: BLE001 - pruning must never fail a chat turn
        db.session.rollback()
        logger.exception("Failed to prune Aqua AI conversations for user=%s", user_id)


# How many RECENT turns of a thread are replayed to the model as context.
#
# CAPPED AT 10 FOR THE SAME REASON THE THREADS ARE CAPPED: the provider meters
# TOKENS per minute, and an unbounded history makes every later turn of a long
# thread progressively larger until the request alone exhausts the budget and
# the provider answers 429. Ten turns is enough for the assistant to follow the
# conversation while keeping the request small and inside the quota.
_MAX_HISTORY_MESSAGES = 10


def _run_llm_turn(client, messages, tools, user_id: int) -> tuple[dict, list, list]:
    """Run one full LLM turn: tool rounds, then the reply.

    Extracted from `send_message` so the rate-limit retry there can call it as
    a unit. Returns (assistant_message, executed_tools, client_actions).

    A SIZE or RATE failure on a tool-bearing turn still has a way through: the
    same question, asked WITHOUT the tool schemas, is a fraction of the payload
    and fits inside the provider's per-minute token budget. Every question that
    does not need the user's own rows - definitions, how the model works,
    general water science, a screen's purpose - is answerable that way, so this
    turns a hard error into a working reply for the common case instead of
    showing "the provider is unavailable".

    Only size/rate/provider failures qualify for the tools-off retry. A timeout
    is a genuine outage and is surfaced as one; a missing key is not retried at
    all (it would fail identically).
    """
    executed_tools: list[dict[str, Any]] = []
    client_actions: list[dict[str, Any]] = []
    try:
        for _ in range(_MAX_TOOL_ROUNDS):
            assistant_message = client.chat(messages, tools=tools)

            tool_calls = assistant_message.get("tool_calls") or []
            if not tool_calls:
                return assistant_message, executed_tools, client_actions

            # Echo the assistant's tool-call turn back so the model retains it.
            messages.append(
                {
                    "role": AI_ROLE_ASSISTANT,
                    "content": assistant_message.get("content"),
                    "tool_calls": tool_calls,
                }
            )

            for call in tool_calls:
                function = call.get("function", {})
                name = function.get("name")
                raw_args = function.get("arguments") or "{}"
                if isinstance(raw_args, str):
                    try:
                        arguments = json.loads(raw_args)
                    except json.JSONDecodeError:
                        arguments = {}

                # Navigation tools are CLIENT-executed: the assistant asks to
                # move, the frontend drives React Router. The target comes from a
                # fixed server-side lookup, never from the model, so an arbitrary
                # URL is not expressible. An unknown name yields no target and the
                # call is dropped rather than forwarded.
                target = get_navigation_target(name)
                if target is not None:
                    action = {"type": "NAVIGATE", "target": target}
                    executed_tools.append(
                        {"name": name, "arguments": action, "executed": False}
                    )
                    result: Any = {"ok": True, **action}
                elif name == "navigate_to_page":
                    # Legacy alias: still validated against the SAME allow-list.
                    route = arguments.get("route")
                    if route in set(NAVIGATION_TARGETS.values()):
                        action = {"type": "NAVIGATE", "target": route}
                        executed_tools.append(
                            {"name": name, "arguments": action, "executed": False}
                        )
                        result = {"ok": True, **action}
                    else:
                        # Reject rather than pass through an unrecognised route.
                        result = {"ok": False, "error": "unknown route"}
                else:
                    result = execute_tool(name, arguments, user_id=user_id)
                    executed_tools.append({"name": name, "arguments": arguments, "executed": True})
                    # A tool result may carry client actions (report downloads).
                    # Collected here rather than derived from the model's text, so
                    # the buttons match the data the tool actually returned.
                    #
                    # DEDUPED BY (type, format, scope). The turn loop allows the
                    # model several rounds, and a model that calls get_report_list
                    # more than once (or calls it once per round) would otherwise
                    # produce the same CSV and PDF button two or three times over.
                    # The button set is identified by what it DOES, so identical
                    # actions collapse to one - the last scope asked for wins,
                    # because that is the filter the model settled on.
                    if isinstance(result, dict):
                        for action in result.get("downloads") or []:
                            if not isinstance(action, dict) or not action.get("type"):
                                continue
                            key = (
                                action.get("type"),
                                action.get("format"),
                                action.get("scope"),
                            )
                            existing = next(
                                (
                                    index
                                    for index, seen in enumerate(client_actions)
                                    if (
                                        seen.get("type"),
                                        seen.get("format"),
                                        seen.get("scope"),
                                    )
                                    == key
                                ),
                                None,
                            )
                            if existing is None:
                                client_actions.append(dict(action))
                            else:
                                client_actions[existing] = dict(action)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "content": json.dumps(result, default=str),
                    }
                )
        else:
            # Loop exhausted without a plain answer; ask once more for text only.
            assistant_message = client.chat(messages, tools=None)
        return assistant_message, executed_tools, client_actions
    except LLMError as exc:
        if exc.kind in ("too_large", "rate_limit", "provider"):
            try:
                assistant_message = client.chat(messages, tools=None)
                logger.info(
                    "Aqua AI answered without tools after a %s failure on a "
                    "tool-bearing turn",
                    exc.kind,
                )
                return assistant_message, executed_tools, client_actions
            except LLMError as retry_exc:
                # The tools-off retry did not help either. Report the ORIGINAL
                # failure, which names the real cause, rather than the retry's.
                raise _llm_error_to_domain(exc) from retry_exc
        else:
            # The transport already classified the failure; surface it as a domain
            # error so a timeout does not read as a generic provider outage.
            raise _llm_error_to_domain(exc) from exc


def send_message() -> dict[str, Any]:
    """Append a user turn, generate the assistant reply, persist both."""
    from app.utils.validators import parse_json_body

    user_id = _current_user_id()
    payload = parse_json_body()

    message_text = payload.get("message") or payload.get("content")
    if not isinstance(message_text, str) or not message_text.strip():
        raise ValidationError("Message is required", {"message": "Enter a message"})

    conversation_id = payload.get("conversation_id")
    if conversation_id is not None:
        try:
            conversation_id = int(conversation_id)
        except (TypeError, ValueError):
            raise ValidationError("conversation_id must be an integer") from None

    conversation = _get_or_create_conversation(user_id, conversation_id)

    # --- Persist the user turn -------------------------------------------
    user_message = AIMessage(
        conversation_id=conversation.id, role=AI_ROLE_USER, content=message_text.strip()
    )
    db.session.add(user_message)

    # First user message names the thread.
    if conversation.title in (None, "", "New conversation"):
        conversation.title = _title_from(message_text)
    db.session.commit()

    # --- Build context ----------------------------------------------------
    # Only the LAST `_MAX_HISTORY_MESSAGES` turns are replayed. The provider
    # meters tokens per minute, so replaying an unbounded history made long
    # threads progressively more likely to be refused with 429.
    all_history = [
        {"role": m.role, "content": m.content}
        for m in conversation.messages.order_by(AIMessage.id).all()
    ]
    history = all_history[-_MAX_HISTORY_MESSAGES:]
    messages = build_conversation_context(history)

    # --- Classify the request ---------------------------------------------
    # `has_context` is True when there is an EARLIER turn to refer back to. The
    # current user message has already been persisted above, so a single entry in
    # `history` means this is the first turn of an empty thread. Without this
    # distinction a follow-up like "Why is it important?" carries no keyword and
    # was classified out-of-scope, i.e. refused.
    earlier_turns = len(history) > 1
    intent = classify_intent(message_text, has_context=earlier_turns)
    logger.info(
        "Aqua AI turn classified intent=%s has_context=%s user=%s",
        intent,
        earlier_turns,
        user_id,
    )

    # --- Provider availability -------------------------------------------
    client = _get_client()
    if not current_app.config.get("AI_ENABLED", True) or not client.is_configured():
        # Honest failure: never fabricate a reply.
        reply = AIMessage(
            conversation_id=conversation.id,
            role=AI_ROLE_ASSISTANT,
            content=(
                "Aqua AI is not connected: no LLM provider is configured. "
                "Set AQUA_AI_API_KEY in the backend .env to enable the assistant."
            ),
        )
        db.session.add(reply)
        db.session.commit()
        return {
            "conversation_id": conversation.id,
            "message": reply.to_dict(),
            "status": AI_MESSAGE_STATUS_ERROR,
            "tool_calls": [],
        }

    tools = get_ai_tool_specs()
    executed_tools: list[dict[str, Any]] = []
    # Client-side action descriptors collected from tool results. These are things
    # the SERVER does not do - navigation and report downloads - which the React
    # client performs. Keeping them in their own list means the reply can carry
    # both the spoken answer and the controls that go with it.
    client_actions: list[dict[str, Any]] = []

    # --- LLM loop (allows the model to call tools then answer) ------------
    # A rate-limited turn is RETRIED once after a short pause rather than
    # reported immediately: free provider tiers budget tokens per minute, and
    # most refusals clear within seconds. The user then sees an answer instead
    # of a "try again shortly" message most of the time.
    _RATE_LIMIT_RETRIES = 1
    _RATE_LIMIT_PAUSE_SECONDS = 8
    for attempt in range(_RATE_LIMIT_RETRIES + 1):
        try:
            assistant_message, executed_tools, client_actions = _run_llm_turn(
                client, messages, tools, user_id
            )
            break
        except LLMError as exc:
            if exc.kind == "rate_limit" and attempt < _RATE_LIMIT_RETRIES:
                logger.info(
                    "Aqua AI provider rate-limited a turn (attempt %d); pausing %ds and retrying",
                    attempt + 1,
                    _RATE_LIMIT_PAUSE_SECONDS,
                )
                time.sleep(_RATE_LIMIT_PAUSE_SECONDS)
                continue
            raise _llm_error_to_domain(exc) from exc

    content = assistant_message.get("content") or ""


    # --- Natural-language navigation fallback -----------------------------
    # If the user clearly asked to go somewhere but the model did not request
    # navigation, resolve the request here. This is what makes the documented
    # phrasings dependable rather than best-effort: the deterministic router
    # recognises them even when the model hesitates or answers without acting.
    #
    # It only runs when the model did NOT already navigate, so a model that
    # handled it correctly is never overridden.
    already_navigating = any(
        not call.get("executed")
        and isinstance(call.get("arguments"), dict)
        and call["arguments"].get("type") == "NAVIGATE"
        for call in executed_tools
    )
    if not already_navigating:
        fallback_target = resolve_navigation_intent(message_text)
        if fallback_target is not None:
            executed_tools.append(
                {
                    "name": NAVIGATION_TOOL_FOR_TARGET.get(fallback_target, "navigate"),
                    "arguments": {"type": "NAVIGATE", "target": fallback_target},
                    "executed": False,
                }
            )
            # A navigation request must always get a spoken reply. If the model
            # returned nothing, name the destination instead of navigating
            # silently.
            if not content.strip():
                content = f"Sure, opening the {NAVIGATION_LABELS[fallback_target]} page."

    # --- Deterministic "explain my latest prediction" fallback -------------
    # Same principle as the navigation fallback above. "Explain my latest
    # prediction" is a documented capability, so it must work even when the
    # model answers without calling the tool. The explanation itself is built
    # by the tool from the stored row - this only guarantees the tool runs.
    #
    # Skipped when the model already called it, so a correct model turn is never
    # duplicated, and skipped when the account has no rows: the tool's own empty
    # state is then surfaced rather than an explanation of nothing.
    already_explaining = any(
        call.get("name") == EXPLAIN_TOOL_NAME for call in executed_tools
    )
    if not already_explaining:
        explain_tool = resolve_explain_intent(message_text)
        if explain_tool is not None:
            result = execute_tool(explain_tool, {}, user_id=user_id)
            executed_tools.append(
                {"name": explain_tool, "arguments": {}, "executed": True}
            )
            prediction = (result or {}).get("prediction") or {}
            explanation = prediction.get("explanation") or {}
            if result.get("empty"):
                # No records: say exactly that, never an improvised explanation.
                content = result.get("message") or content
            else:
                # The tool's wording is authoritative - it is the only text that
                # is guaranteed to match the stored verdict and readings.
                content = explanation.get("text") or content
                if explanation.get("warning"):
                    content = content.rstrip() + "\n\n" + explanation["warning"]

    if not content.strip():
        content = "I could not produce a reply just now."

    # --- Safety pass on the outgoing reply ---------------------------------
    # Two rules are enforced mechanically rather than trusted to the model:
    #
    #   1. Secrets never leave the server. Whatever the provider returned, a key
    #      or token in it is replaced before the reply is stored or sent.
    #   2. A request that asks for secrets, SQL/code execution, or tries to
    #      override these rules gets a fixed refusal. The model is instructed to
    #      decline, but a fixed sentence makes it certain - and it avoids the
    #      model explaining what it would have done, which is the leak.
    #
    # Neither check can add or reword anything else, so a normal answer passes
    # through untouched.
    refusal = refusal_for(message_text)
    if refusal and not executed_tools:
        # Only when no tool ran: a request that merely mentions a banned phrase
        # inside a genuine question which already produced real data should not
        # discard that data. With no data to protect, the fixed refusal wins.
        content = refusal
    content = redact_secrets(content)

    reply = AIMessage(
        conversation_id=conversation.id, role=AI_ROLE_ASSISTANT, content=content
    )
    db.session.add(reply)
    db.session.commit()

    return {
        "conversation_id": conversation.id,
        "message": reply.to_dict(),
        "status": AI_MESSAGE_STATUS_OK,
        "tool_calls": executed_tools,
        "client_actions": client_actions,
    }


def chat() -> dict[str, Any]:
    """Chat entry point returning the client-facing envelope.

    Implements the documented request flow, in order:

        authenticate (JWT, enforced by the route)
          -> validate message
          -> load Aqua AI system prompt
          -> load relevant project knowledge
          -> load conversation context
          -> call the configured LLM
          -> process the response (resolve tool calls)
          -> return the reply
    Returns the shape the client contract specifies::

        {
          "success": true,
          "message": "...",
          "conversation_id": "...",
          "actions": []
        }

    `actions` carries any client-side effects the model requested (today, only
    navigation). Server-side tool calls have already run by the time this returns.

    Every provider failure is translated here rather than leaking transport detail:
    a missing key becomes a 503, a timeout 504, a rate limit 429, and any other
    provider or malformed-response failure a 502. Nothing about the API key is ever
    included in the message.
    """
    # --- 1. Validate the message first -----------------------------------
    # Order matters: a malformed or empty body must be rejected as 400/422 even
    # when the deployment also lacks a provider key. Checking configuration
    # first would mask a client's own mistake behind an unrelated 503.
    from app.utils.validators import parse_json_body
    payload = parse_json_body()
    message_text = payload.get("message") or payload.get("content")
    if not isinstance(message_text, str) or not message_text.strip():
        raise ValidationError("Message is required", {"message": "Enter a message"})

    # --- 2. Ownership, before anything else ------------------------------
    # If the caller named a thread, prove it is theirs BEFORE the provider gate.
    # A foreign id must be indistinguishable from a missing one (404) regardless
    # of whether the assistant is configured — the alternative leaks the
    # existence of another account's thread through a different status code.
    conversation_id = payload.get("conversation_id")
    if conversation_id is not None:
        try:
            conversation_id = int(conversation_id)
        except (TypeError, ValueError):
            raise ValidationError("conversation_id must be an integer") from None
        _assert_owns_conversation(_current_user_id(), conversation_id)

    # --- 3. Provider availability ----------------------------------------
    # Checked BEFORE touching the conversation, so a deployment with no key
    # fails as a clear 503 rather than silently creating a thread and answering
    # with a placeholder that looks like a reply.
    client = _get_client()
    if not current_app.config.get("AI_ENABLED", True) or not client.is_configured():
        raise _llm_error_to_domain(
            LLMError("missing_key", "No LLM provider is configured")
        )

    # --- 4. Run the turn --------------------------------------------------
    try:
        result = send_message()
    except LLMError as exc:
        raise _llm_error_to_domain(exc) from exc
    # --- 5. Collect client-side actions ----------------------------------
    # Only client-executed calls are surfaced as actions; server-side tools have
    # already produced their effect by the time this returns.
    #
    # Two sources, deliberately merged into one list:
    #   * NAVIGATE actions, from the tool calls that were not executed server-side;
    #   * DOWNLOAD_REPORTS actions, carried back by a tool result (get_report_list).
    #
    # The client switches on `type`. Both are fixed vocabularies - a route from the
    # navigation allow-list, a format of csv|pdf, a scope of all|safe|moderate|
    # unsafe - so no part of this can name an arbitrary URL, path or file.
    actions = [
        dict(call.get("arguments") or {})
        for call in (result.get("tool_calls") or [])
        if not call.get("executed")
        and isinstance(call.get("arguments"), dict)
        and call["arguments"].get("type") == "NAVIGATE"
    ]
    for action in result.get("client_actions") or []:
        actions.append(dict(action))

    message = result.get("message") or {}

    return {
        "success": True,
        "message": message.get("content", ""),
        "conversation_id": str(result.get("conversation_id")),
        "actions": actions,
    }


def _llm_error_to_domain(exc: LLMError) -> AquaGuardError:
    """Map a transport-level `LLMError` onto a domain error with the right status.

    Chosen so the client can branch meaningfully:

        missing_key  -> 503  the assistant is not configured on this deployment
        timeout      -> 504  the provider did not answer in time
        rate_limit   -> 429  quota exhausted; the client should back off
        provider     -> 502  the provider answered with an error
        malformed    -> 502  the provider answered with something unreadable
    The message text is a fixed, user-safe string. Nothing from the upstream
    request or response is echoed, so a key or header can never reach the client.
    """
    kind = exc.kind
    if kind == "missing_key":
        return ServiceUnavailableError(
            "Aqua AI is not configured on this server. Set AQUA_AI_API_KEY in the "
            "backend environment to enable the assistant."
        )
    if kind == "timeout":
        # 504: the failure is time spent waiting on an upstream, not our own bug.
        return UpstreamTimeoutError(
            "Aqua AI took too long to respond. Please try again."
        )
    if kind == "rate_limit":
        return RateLimitError(
            "Aqua AI is rate limiting requests right now. Please try again shortly."
        )
    if kind == "too_large":
        # 413: the provider's per-minute token budget could not hold the request
        # even after the tool schemas were dropped. Rate-limit-adjacent (it is a
        # quota, and waiting helps), so it maps to 429 rather than a 5xx.
        return RateLimitError(
            "Aqua AI is busy right now. Please try again in a moment."
        )
    if kind == "malformed":
        return ExternalServiceError("Aqua AI returned an unreadable response.")

    return ExternalServiceError("Aqua AI provider is unavailable")


def list_conversations(page: int, per_page: int) -> tuple[list, dict]:
    """Return a paginated page of the caller's conversations."""
    user_id = _current_user_id()

    query = (
        AIConversation.query.filter_by(user_id=user_id)
        .order_by(AIConversation.updated_at.desc(), AIConversation.id.desc())
    )

    items, meta = paginate_query(query, page, per_page)
    return [_serialize_conversation(item) for item in items], meta


def create_conversation() -> dict[str, Any]:
    """Create a new empty conversation thread."""
    user_id = _current_user_id()

    conversation = AIConversation(user_id=user_id, title="New conversation")
    db.session.add(conversation)
    db.session.commit()

    return _serialize_conversation(conversation, include_messages=True)


def get_conversation(conversation_id: int) -> dict[str, Any]:
    """Return one conversation with its ordered messages."""
    conversation = _assert_owns_conversation(_current_user_id(), conversation_id)
    return _serialize_conversation(conversation, include_messages=True)


def delete_conversation(conversation_id: int) -> None:
    """Delete a conversation and all of its messages."""
    user_id = _current_user_id()
    conversation = _assert_owns_conversation(user_id, conversation_id)

    try:
        db.session.delete(conversation)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to delete conversation=%s", conversation_id)
        raise

    logger.info("Conversation deleted: id=%s user=%s", conversation_id, user_id)
