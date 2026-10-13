"""Aqua AI blueprint — the conversational assistant.

    POST   /api/v1/ai/chat                      send a message, get a reply
    GET    /api/v1/ai/conversations             list the caller's conversations
    POST   /api/v1/ai/conversations             start a new conversation
    GET    /api/v1/ai/conversations/<id>        full message history
    DELETE /api/v1/ai/conversations/<id>        delete a conversation
    GET    /api/v1/ai/tools                     the controlled tool catalogue

Aqua AI never executes application actions itself: it may only *request* a tool
from the registry in `utils.ai_tools`, which the client or a service then runs
under the caller's own permissions.

NO TOKEN IS REQUIRED on any of these. The application is open, so a conversation
is filed under whatever account the request resolves to - see
`app.services.identity`.
"""

from flask import Blueprint

from app.utils.ai_tools import get_ai_tool_specs
from app.utils.errors import AquaGuardError
from app.utils.pagination import parse_pagination
from app.utils.responses import error_response, success_response

ai_bp = Blueprint("ai", __name__)


@ai_bp.post("/chat")
@ai_bp.post("/aqua-ai/chat", endpoint="aqua_ai_chat")
def chat():
    """Append a user turn, generate a reply, and persist both.

    Served at two paths, one implementation:

        POST /api/aqua-ai/chat         the canonical path the React client calls
        POST /api/ai/aqua-ai/chat      the unversioned equivalent
        POST /api/v1/ai/aqua-ai/chat   the versioned equivalent

    Both reach this function, so the assistant cannot behave differently
    depending on which URL a caller happened to use.
    """
    try:
        from app.services.ai_service import chat as run_chat
        return success_response(data=run_chat(), message="Aqua AI replied")
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)


@ai_bp.get("/conversations")
def list_conversations():
    """List conversations for the chat sidebar."""
    try:
        from app.services.ai_service import list_conversations as list_convs

        page, per_page = parse_pagination(default_per_page=50)
        items, meta = list_convs(page, per_page)
        return success_response(data=items, meta=meta)
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)


@ai_bp.post("/conversations")
def create_conversation():
    """Explicitly start a new conversation thread."""
    try:
        from app.services.ai_service import create_conversation as create_conv

        return success_response(
            data=create_conv(), message="Conversation created", status_code=201
        )
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)


@ai_bp.get("/conversations/<int:conversation_id>")
def get_conversation(conversation_id: int):
    """Return one conversation with its ordered messages."""
    try:
        from app.services.ai_service import get_conversation as fetch_conv

        return success_response(data=fetch_conv(conversation_id))
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)


@ai_bp.delete("/conversations/<int:conversation_id>")
def delete_conversation(conversation_id: int):
    """Delete a conversation and all of its messages."""
    try:
        from app.services.ai_service import delete_conversation as remove_conv

        remove_conv(conversation_id)
        return success_response(message="Conversation deleted")
    except AquaGuardError as exc:
        return error_response(exc.message, exc.status_code, exc.errors)


@ai_bp.get("/tools")
def list_tools():
    """Expose the controlled tool catalogue for client-side execution."""
    return success_response(data=get_ai_tool_specs())
