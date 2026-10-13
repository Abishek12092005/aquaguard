"""Pagination helpers used by history, alerts and AI conversation listings."""

from flask import request

from app.constants import DEFAULT_PAGE, DEFAULT_PER_PAGE, MAX_PER_PAGE


def parse_pagination(default_per_page: int = DEFAULT_PER_PAGE) -> tuple[int, int]:
    """Read and clamp `page` / `per_page` query parameters."""
    try:
        page = int(request.args.get("page", DEFAULT_PAGE))
    except (TypeError, ValueError):
        page = DEFAULT_PAGE

    try:
        per_page = int(request.args.get("per_page", default_per_page))
    except (TypeError, ValueError):
        per_page = default_per_page

    page = max(1, page)
    per_page = max(1, min(per_page, MAX_PER_PAGE))
    return page, per_page


def paginate_query(query, page: int, per_page: int) -> tuple[list, dict]:
    """Run a paginated SQLAlchemy query and return (items, meta)."""
    from app.extensions import db
    if hasattr(query, "paginate"):
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    else:
        pagination = db.paginate(query, page=page, per_page=per_page, error_out=False)
    meta = {
        "page": pagination.page,
        "per_page": pagination.per_page,
        "total": pagination.total,
        "pages": pagination.pages,
        "has_next": pagination.has_next,
        "has_prev": pagination.has_prev,
    }
    return pagination.items, meta
