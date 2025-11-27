# app/__init__.py
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from config import Config

# Global DB objects so other modules can import them
db = SQLAlchemy()
migrate = Migrate()

def create_app():
    """Application factory: creates and configures the Flask app."""
    app = Flask(__name__)
    app.config.from_object(Config)

    # Attach DB + migrations to this app
    db.init_app(app)
    migrate.init_app(app, db)

    # Import models so SQLAlchemy knows the tables
    from . import models  # noqa: F401  # we just need to import, not use directly

    # ✅ Ensure all tables exist (important on Render where no 'flask db upgrade' is run)
    with app.app_context():
        db.create_all()  # creates tables defined in models.py if they don't exist

    # Register the main blueprint (your routes)
    from .routes import bp as main_bp
    app.register_blueprint(main_bp)

    return app
