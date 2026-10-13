"""SQLAlchemy ORM models — mirror of database/schema.sql.

Every model module is imported here so a single `from app import models`
registers the full metadata with SQLAlchemy.

The five tables below are exactly the tables in the schema. There are no extra
models and no extra columns: an ORM that expects something the database does not
have fails at query time with a confusing "Unknown column", so the schema is
treated as the contract rather than a suggestion.

    users                   accounts
    water_predictions       readings + model verdict
    alerts                  unsafe-water notifications
    aqua_ai_conversations   chat threads
    aqua_ai_messages        chat turns
    login_events            sign-in history (append-only)
    admin_settings          single-row admin console state
    admin_login_approvals   one row per admin login awaiting an emailed decision
    model_versions          registered ML model artifacts and their validation state
    model_audit_logs        append-only trail of every registry change
        report_email_audits     append-only trail of report-download-by-email requests
        location_scope_audits   append-only trail of admin scope changes (PROMPT 13)
        """

from app.models.admin_login_approval import AdminLoginApproval
from app.models.admin_settings import AdminSettings
from app.models.ai_conversation import AIConversation
from app.models.ai_message import AIMessage
from app.models.alert import Alert
from app.models.login_event import LoginEvent
from app.models.location_scope_audit import LocationScopeAudit
from app.models.model_version import ModelAuditLog, ModelVersion
from app.models.report_email_audit import ReportEmailAudit
from app.models.user import User
from app.models.water_prediction import WaterPrediction
__all__ = [
    "AdminLoginApproval",
    "AdminSettings",
    "AIConversation",
    "AIMessage",
    "Alert",
    "LoginEvent",
    "LocationScopeAudit",
    "ModelAuditLog",
    "ModelVersion",
    "ReportEmailAudit",
    "User",
    "WaterPrediction",
]
