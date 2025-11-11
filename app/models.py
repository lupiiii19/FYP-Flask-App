# app/models.py
from datetime import datetime
from . import db

class SearchLog(db.Model):
    """
    Stores one row per user search for analytics/monitoring.
    """
    id = db.Column(db.Integer, primary_key=True)
    query = db.Column(db.String(300), nullable=False)        # what the user typed
    results_count = db.Column(db.Integer, default=0)         # how many items we showed
    top_text = db.Column(db.Text)                            # short preview of top result (optional)
    latency_ms = db.Column(db.Integer)                       # request latency (ms)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
