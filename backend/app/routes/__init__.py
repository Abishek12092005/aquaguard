"""Flask blueprints — one module per resource, grouped by feature area.

Blueprints are imported by the application factory and mounted under
`/api/v1`. Keeping routing separate from business logic means the same service
can be reused by the REST API and by Aqua AI tool execution.
"""

from app.routes.ai_routes import ai_bp
from app.routes.alert_routes import alerts_bp
from app.routes.dashboard_routes import dashboard_bp
from app.routes.health_routes import health_bp
from app.routes.prediction_routes import predictions_bp
from app.routes.location_routes import location_bp
__all__ = [
    "ai_bp",
    "alerts_bp",
    "dashboard_bp",
    "health_bp",
    "predictions_bp",
    "location_bp",
]
