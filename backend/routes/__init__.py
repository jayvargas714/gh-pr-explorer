"""Route blueprints registration."""

from backend.routes.static_routes import static_bp
from backend.routes.auth_routes import auth_bp
from backend.routes.repo_routes import repo_bp
from backend.routes.pr_routes import pr_bp
from backend.routes.analytics_routes import analytics_bp
from backend.routes.workflow_routes import workflow_bp
from backend.routes.queue_routes import queue_bp
from backend.routes.review_routes import review_bp
from backend.routes.history_routes import history_bp
from backend.routes.settings_routes import settings_bp
from backend.routes.cache_routes import cache_bp


def register_blueprints(app):
    """Register all route blueprints with the Flask app."""
    app.register_blueprint(static_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(repo_bp)
    app.register_blueprint(pr_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(workflow_bp)
    app.register_blueprint(queue_bp)
    app.register_blueprint(review_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(cache_bp)
