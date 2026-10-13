"""Cross-cutting helpers shared by routes, services and the ML pipeline."""

from app.utils.ai_tools import AI_TOOL_SPECS, get_ai_tool_specs
from app.utils.errors import (
    AquaGuardError,
    ConflictError,
    ForbiddenError,
    MLModelError,
    NotFoundError,
    ValidationError,
)
from app.utils.pagination import paginate_query, parse_pagination
from app.utils.responses import error_response, success_response
from app.utils.validators import (
    validate_email,
    validate_password_strength,
    validate_water_quality_payload,
)

__all__ = [
    "AI_TOOL_SPECS",
    "AquaGuardError",
    "ConflictError",
    "ForbiddenError",
    "MLModelError",
    "NotFoundError",
    "ValidationError",
    "error_response",
    "get_ai_tool_specs",
    "paginate_query",
    "parse_pagination",
    "success_response",
    "validate_email",
    "validate_password_strength",
    "validate_water_quality_payload",
]
