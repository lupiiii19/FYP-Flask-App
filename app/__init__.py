# app/__init__.py
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from config import Config

# Create global DB/migrate objects (imported by other modules)
db = SQLAlchemy()
migrate = Migrate()

def create_app():
    # App factory pattern keeps things clean and testable
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize database and migrations with this app
    db.init_app(app)
    migrate.init_app(app, db)

    # Import models so Alembic (migrate) can "see" them
    from . import models  # noqa: F401

    # Register your blueprint routes
    from .routes import bp as main_bp
    app.register_blueprint(main_bp)

    return app
