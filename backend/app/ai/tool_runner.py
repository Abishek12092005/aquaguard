"""Controlled tool execution for Aqua AI.

The assistant cannot touch the database or the router directly. It may only
reference a tool by name from `app.utils.ai_tools`; this module validates the
call against that catalogue and dispatches it to a registered handler running
under the *user's own* permissions.

Tool handlers are registered in `AVAILABLE_TOOLS`. Keeping the registry here
(not in the prompt) means an unknown or hallucinated tool name is rejected
before it can do anything.
"""

import logging
from typing import Any, Callable

from app.utils.ai_tools import get_tool_names
from app.utils.errors import ForbiddenError, ValidationError

logger = logging.getLogger(__name__)

ToolHandler = Callable[..., Any]


def resolve_tool(name: str) -> str:
    """Validate a requested tool name against the catalogue.

    Raises `ForbiddenError` for anything not declared, so a model cannot widen
    its own capabilities by inventing a function name.
    """
    if not isinstance(name, str) or not name:
        raise ValidationError("Tool name is required")

    allowed = get_tool_names()
    if name not in allowed:
        logger.warning("Aqua AI requested unknown tool %r", name)
        raise ForbiddenError(
            f"Tool {name!r} is not available",
            {"available_tools": allowed},
        )
    return name


# --------------------------------------------------------------------------
# Tool registry
# --------------------------------------------------------------------------
# Each handler receives the validated argument dict and the authenticated
# user's id. Handlers are registered lazily by the service layer in Phase 2;
# the mapping is the single extension point for new capabilities.
AVAILABLE_TOOLS: dict[str, ToolHandler] = {}


def register_tool(name: str, handler: ToolHandler) -> None:
    """Register a handler for a catalogued tool."""
    resolve_tool(name)  # fail fast on typos at registration time
    AVAILABLE_TOOLS[name] = handler


def execute_tool(name: str, arguments: dict[str, Any] | None = None, user_id: int | None = None) -> Any:
    """Validate and run a catalogued tool.

    Returns the handler's result, which the caller feeds back to the model as a
    `tool` message. Unknown tools and unregistered handlers fail loudly rather
    than silently returning empty data.
    """
    resolved = resolve_tool(name)
    handler = AVAILABLE_TOOLS.get(resolved)

    if handler is None:
        raise ForbiddenError(
            f"Tool {resolved!r} has no registered handler",
            {"tool": resolved},
        )

    logger.info("Aqua AI executing tool %s for user=%s", resolved, user_id)
    return handler(**(arguments or {}), user_id=user_id)
