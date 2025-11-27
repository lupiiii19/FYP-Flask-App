# app/routes.py
import time
from flask import Blueprint, render_template, request, jsonify, current_app
from .services.recommender import ensure_models_loaded, recommend_topk
from .models import SearchLog
from . import db
from sqlalchemy import func, desc

bp = Blueprint("main", __name__)

@bp.route("/")
def index():
    # Home stays lightweight—no model load here
    return render_template("index.html")

 
@bp.route("/recommend", methods=["GET", "POST"])
def recommend_page():
    """
    GET  -> just render the form (do NOT try to load models yet)
    POST -> try to load models and compute results; show friendly errors
    """
    load_error = None
    results = None
    query = ""
    topk = 5

    if request.method == "POST":
        query = (request.form.get("query") or "").strip()
        try:
            topk = int(request.form.get("topk") or 5)
        except ValueError:
            topk = 5
        # Clamp to a reasonable range
        topk = max(1, min(topk, 50))

        try:
            # Only load/build the model when the user actually searches
            ensure_models_loaded()
            if query:
                results = recommend_topk(query, topk)
        except Exception as e:
            # Any error (e.g., no CSV on server) shows up as a friendly banner
            current_app.logger.exception("Model load or recommend failed")
            load_error = "There was a problem preparing the model. Please try again later."

    # On GET, or if error happened, we still render the page
    return render_template(
        "results.html",
        query=query,
        results=results,
        topk=topk,
        load_error=load_error,
    )


@bp.route("/api/recommend")
def api_recommend():
    # JSON API mirrors the UI behavior
    try:
        ensure_models_loaded()
    except Exception:
        current_app.logger.exception("Model load failed for API")
        return jsonify({"error": "Model not available"}), 503

    query = (request.args.get("query") or "").strip()
    try:
        topk = int(request.args.get("topk", 5))
    except (ValueError, TypeError):
        topk = 5
    topk = max(1, min(topk, 50))
    if not query:
        return jsonify({"error": "query is required"}), 400

    t0 = time.perf_counter()
    results = recommend_topk(query, topk)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    # Log the API call too
    top_text = (results[0]["text"][:120] + "…") if results else None
    try:
        db.session.add(SearchLog(query=query, results_count=len(results), top_text=top_text, latency_ms=latency_ms))
        db.session.commit()
    except Exception:
        current_app.logger.exception("Failed to log API search")

    return jsonify(results)

@bp.route("/admin/analytics")
def analytics():
    """
    Simple analytics page.
    Shows totals, average latency, top queries, and recent logs.
    If anything goes wrong with the DB, show a friendly message instead of 500.
    """
    error = None
    total = 0
    avg_latency = 0
    top_queries = []
    recent = []

    try:
        # Total number of logged searches
        total = db.session.query(func.count(SearchLog.id)).scalar() or 0

        # Average latency (ms)
        avg_latency = db.session.query(func.avg(SearchLog.latency_ms)).scalar() or 0

        # Top queries (grouped by query text)
        top_queries = (
            db.session.query(SearchLog.query, func.count(SearchLog.id).label("n"))
            .group_by(SearchLog.query)
            .order_by(desc("n"))
            .limit(10)
            .all()
        )

        # Most recent 20 log entries
        recent = (
            db.session.query(SearchLog)
            .order_by(desc(SearchLog.created_at))
            .limit(20)
            .all()
        )

    except Exception as e:
        # If anything fails (e.g. DB issue), capture it and display on the page
        error = str(e)

    return render_template(
        "analytics.html",
        total=int(total or 0),
        avg_latency=int(avg_latency or 0),
        top_queries=top_queries,
        recent=recent,
        error=error,   # pass the error (if any) to the template
    )
