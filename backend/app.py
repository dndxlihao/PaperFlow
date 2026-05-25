import os
import sys

from flask import Flask, send_from_directory
from flask_cors import CORS
from sqlalchemy import inspect, text

from config import Config
from models import db

# Frontend build directory
FRONTEND_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "dist")
AVATARS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pic", "avatars")
ABOUT_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pic", "about")


def _ensure_user_profile_columns():
    inspector = inspect(db.engine)
    columns = {col["name"] for col in inspector.get_columns("users")}
    statements = []

    if "display_name" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN display_name VARCHAR(80) NULL")
    if "avatar_url" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN avatar_url VARCHAR(500) NULL")
    if "profile_bio" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN profile_bio TEXT NULL")
    if "profile_research_areas_json" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN profile_research_areas_json TEXT NULL")

    for statement in statements:
        db.session.execute(text(statement))

    if statements:
        db.session.commit()


def _ensure_paper_edit_request_columns():
    inspector = inspect(db.engine)
    if "paper_edit_requests" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("paper_edit_requests")}
    statements = []

    if "target_field" not in columns:
        statements.append("ALTER TABLE paper_edit_requests ADD COLUMN target_field VARCHAR(40) NULL")
    if "selected_text" not in columns:
        statements.append("ALTER TABLE paper_edit_requests ADD COLUMN selected_text TEXT NULL")
    if "suggestion_text" not in columns:
        statements.append("ALTER TABLE paper_edit_requests ADD COLUMN suggestion_text TEXT NULL")

    for statement in statements:
        db.session.execute(text(statement))

    if statements:
        db.session.commit()


def _ensure_paper_creator_columns():
    inspector = inspect(db.engine)
    if "papers" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("papers")}
    statements = []

    if "content_origin" not in columns:
        statements.append("ALTER TABLE papers ADD COLUMN content_origin VARCHAR(30) NULL")
    if "created_by_user_id" not in columns:
        statements.append("ALTER TABLE papers ADD COLUMN created_by_user_id INT NULL")
    if "processing_status" not in columns:
        statements.append("ALTER TABLE papers ADD COLUMN processing_status VARCHAR(20) NULL")
    if "processing_error" not in columns:
        statements.append("ALTER TABLE papers ADD COLUMN processing_error TEXT NULL")
    if "creator_review_status" not in columns:
        statements.append("ALTER TABLE papers ADD COLUMN creator_review_status VARCHAR(20) NULL")
    if "creator_review_note" not in columns:
        statements.append("ALTER TABLE papers ADD COLUMN creator_review_note TEXT NULL")
    if "creator_reviewed_by" not in columns:
        statements.append("ALTER TABLE papers ADD COLUMN creator_reviewed_by INT NULL")
    if "creator_reviewed_at" not in columns:
        statements.append("ALTER TABLE papers ADD COLUMN creator_reviewed_at DATETIME NULL")

    for statement in statements:
        db.session.execute(text(statement))

    # Backfill old rows to stable defaults.
    db.session.execute(text(
        "UPDATE papers SET content_origin='system' "
        "WHERE content_origin IS NULL OR TRIM(content_origin) = ''"
    ))
    db.session.execute(text(
        "UPDATE papers SET processing_status='ready' "
        "WHERE processing_status IS NULL OR TRIM(processing_status) = ''"
    ))
    db.session.execute(text(
        "UPDATE papers SET creator_review_status='approved' "
        "WHERE creator_review_status IS NULL OR TRIM(creator_review_status) = ''"
    ))
    db.session.commit()


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)

    # Ensure PDF directory exists
    os.makedirs(app.config["PDF_DIR"], exist_ok=True)
    os.makedirs(AVATARS_DIR, exist_ok=True)
    os.makedirs(ABOUT_ASSETS_DIR, exist_ok=True)

    # Extensions
    CORS(app, supports_credentials=True)
    db.init_app(app)

    # Blueprints
    from auth import auth_bp
    from papers import papers_bp
    from recommend import recommend_bp
    from friends import friends_bp
    from groups import groups_bp
    from knowledge import knowledge_bp
    from scholars import scholars_bp
    from admin import admin_bp
    from about import about_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(papers_bp)
    app.register_blueprint(recommend_bp)
    app.register_blueprint(friends_bp)
    app.register_blueprint(groups_bp)
    app.register_blueprint(knowledge_bp)
    app.register_blueprint(scholars_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(about_bp)

    # Create tables
    with app.app_context():
        db.create_all()
        _ensure_user_profile_columns()
        _ensure_paper_edit_request_columns()
        _ensure_paper_creator_columns()

    # Serve paper figures
    FIGURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "figures")

    @app.route("/api/figures/<path:filename>")
    def serve_figure(filename):
        return send_from_directory(os.path.abspath(FIGURES_DIR), filename)

    @app.route("/api/avatars/<path:filename>")
    def serve_avatar(filename):
        return send_from_directory(os.path.abspath(AVATARS_DIR), filename)

    @app.route("/api/about-assets/<path:filename>")
    def serve_about_assets(filename):
        return send_from_directory(os.path.abspath(ABOUT_ASSETS_DIR), filename)

    # Serve frontend SPA — catch-all for non-API routes
    @app.route("/assets/<path:filename>")
    def serve_assets(filename):
        return send_from_directory(os.path.join(FRONTEND_DIST, "assets"), filename)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_frontend(path):
        file_path = os.path.join(FRONTEND_DIST, path)
        if path and os.path.isfile(file_path):
            return send_from_directory(FRONTEND_DIST, path)
        return send_from_directory(FRONTEND_DIST, "index.html")

    # Scheduler (only in main process, not reloader)
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or "gunicorn" in sys.modules:
        from scheduler import init_scheduler
        init_scheduler(app)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
