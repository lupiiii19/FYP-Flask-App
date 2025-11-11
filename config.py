# config.py
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "Dataset"  # <- where your CSV/PKL live

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret")
    # SQLite file in your project root (fyp.db). Easy to copy/backup.
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{BASE_DIR / 'fyp.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False  # avoid noisy warnings
