"""Service layer — business logic between the REST routes and the data layer.

Each service module owns one bounded responsibility and is the only place that
knows how a feature works end-to-end. Routes stay thin, and the same functions
are reused for Aqua AI tool execution.

Implementation status per module (Phase 1 = scaffold, signatures + contracts
fixed; Phase 2 fills the bodies):

    prediction_service  -> validate -> predict -> persist -> alert
    alert_service       -> raise / list / acknowledge / resolve
    dashboard_service   -> aggregates + chart series
    identity            -> who a request acts as: a token's account, or the
                          shared visitor (the application has no user login)
    ai_service          -> conversation context + tool calls

There is deliberately no `auth_service` or `profile_service`: normal users have
no account, no login and no profile. The admin console is authenticated by its
own credential in `admin_service` + `console_session`, and nothing else.
"""

__all__ = [
    "ai_service",
    "alert_service",
    "dashboard_service",
    "identity",
    "prediction_service",
]
