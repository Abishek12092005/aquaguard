"""Aqua AI package — the conversational assistant.

    client.py          provider-agnostic LLM transport (OpenAI-compatible)
    prompts.py         system prompt + conversation-context assembly
    tool_runner.py     validates and dispatches controlled application tools

Design rule: the assistant *proposes*, the application *executes*. The model
may only reference tools declared in `app.utils.ai_tools`, and every tool call
is validated against that catalogue before anything happens — so the assistant
can drive navigation without ever holding a database handle or a router.
"""

from app.ai.client import LLMClient, get_llm_client
from app.ai.prompts import build_conversation_context, build_system_prompt
from app.ai.tool_runner import AVAILABLE_TOOLS, execute_tool, resolve_tool

__all__ = [
    "AVAILABLE_TOOLS",
    "LLMClient",
    "build_conversation_context",
    "build_system_prompt",
    "execute_tool",
    "get_llm_client",
    "resolve_tool",
]
