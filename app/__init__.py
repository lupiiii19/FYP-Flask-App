# app/__init__.py
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from config import Config

# Global DB objects so other modules can import them
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()

def create_app():
    """Application factory: creates and configures the Flask app."""
    app = Flask(__name__)
    app.config.from_object(Config)

    # Attach DB + migrations to this app
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # where to redirect if a non-logged-in user hits @login_required
    login_manager.login_view = "main.login"   # 'main' = blueprint name, 'login' = function name

    from . import models  # noqa: F401

    @login_manager.user_loader
    def load_user(user_id):
        from .models import User
        return User.query.get(int(user_id))

    with app.app_context():
        db.create_all()

    from .routes import bp as main_bp
    app.register_blueprint(main_bp)

    return app

