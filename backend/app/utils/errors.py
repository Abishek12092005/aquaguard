"""Domain-level exceptions.

Services raise these rather than returning ad-hoc tuples, and the application
error handlers translate them into the standard JSON envelope.

The status codes are chosen so the client can branch meaningfully:

    401  not authenticated  -> present credentials (this includes expired tokens)
    403  authenticated but not allowed
    404  resource does not exist
    409  conflicts with current state (duplicate email)
    422  understood, but the contents are invalid
    503  a dependency (model, database) is unavailable
"""


class AquaGuardError(Exception):
    """Base class for every application-specific error."""

    status_code = 500
    default_message = "Internal application error"

    def __init__(self, message: str | None = None, errors=None):
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        self.errors = errors

    def to_dict(self) -> dict:
        payload = {"message": self.message}
        if self.errors is not None:
            payload["errors"] = self.errors
        return payload


class AuthError(AquaGuardError):
    # Authentication failed.
    #
    # 401 means "who are you?" and tells the client to present credentials.
    # 403 means "I know who you are, and no." The frontend branches on this
    # distinction, so collapsing the two would make an expired session
    # indistinguishable from a permissions problem.

    status_code = 401
    default_message = "Authentication failed"


class BadRequestError(AquaGuardError):
    # 400: the request could not be understood at all — a missing body, a body
    # that is not JSON, or JSON that is not an object. Distinct from 422 below,
    # where the request WAS understood but its values were unacceptable.

    status_code = 400
    default_message = "Bad request"

class ValidationError(AquaGuardError):
    # 422 rather than 400: the request was syntactically valid JSON and was
    # understood, but its contents were unacceptable. A useful distinction
    # when reading logs.

    status_code = 422
    default_message = "Validation failed"


class NotFoundError(AquaGuardError):
    status_code = 404
    default_message = "Resource not found"


class ConflictError(AquaGuardError):
    status_code = 409
    default_message = "Resource already exists"


class ForbiddenError(AquaGuardError):
    status_code = 403
    default_message = "You do not have access to this resource"


class MLModelError(AquaGuardError):
    status_code = 503
    default_message = "Prediction model is unavailable"

class NotImplementedError_(AquaGuardError):
    # A feature whose route exists but whose service body has not been written.
    #
    # 501 rather than 500: the request was well-formed and the caller did
    # nothing wrong — the server simply has not implemented it. Returning 500
    # would send the frontend looking for a bug on its own side, and would show
    # up in logs as a server fault rather than an unfinished endpoint.

    status_code = 501
    default_message = "This feature is not implemented yet"


class ExternalServiceError(AquaGuardError):
    status_code = 502
    default_message = "Upstream service failed"

class ServiceUnavailableError(AquaGuardError):
    # 503: the dependency is not configured or is down, i.e. the server is not
    # currently able to serve the request — distinct from 502, where a reachable
    # upstream returned a bad answer. A missing LLM API key is the canonical case.

    status_code = 503
    default_message = "Service unavailable"

class RateLimitError(AquaGuardError):
    # 429: the caller did nothing wrong, but a dependency (here, the LLM
    # provider) is refusing further requests for now. Distinct from 502 so the
    # client can back off and retry rather than treating it as a hard failure.

    status_code = 429
    default_message = "Too many requests"

class UpstreamTimeoutError(AquaGuardError):
    # 504: we reached the dependency but it did not answer in time. Distinct from
    # 500 (our own bug) and 502 (the dependency answered with an error).

    status_code = 504
    default_message = "Upstream service timed out"
