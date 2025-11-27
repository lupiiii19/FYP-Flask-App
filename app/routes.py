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
    GET  -> just show the form.
    POST -> run the recommender AND log the search into the database.
    """
    load_error = None
    results = None
    query = ""
    topk = 5

    if request.method == "POST":
        # Read form inputs safely
        query = (request.form.get("query") or "").strip()
        try:
            topk = int(request.form.get("topk") or 5)
        except ValueError:
            topk = 5  # fallback

        if query:
            try:
                # Measure how long the recommendation takes
                t0 = time.perf_counter()

                # Make sure dataset/model are ready
                ensure_models_loaded()

                # Get top-k recommendations
                results = recommend_topk(query, topk)

                latency_ms = int((time.perf_counter() - t0) * 1000)

                # Short preview of the top result (for analytics)
                top_text = (results[0]["text"][:120] + "…") if results else None

                # Create a SearchLog row
                log = SearchLog(
                    query=query,
                    results_count=len(results or []),
                    top_text=top_text,
                    latency_ms=latency_ms,
                )
                db.session.add(log)
                db.session.commit()  # actually write to the DB

            except Exception as e:
                # Any error (e.g. dataset missing) -> show friendly message
                load_error = str(e)

    return render_template(
        "results.html",
        query=query,
        results=results,
        topk=topk,
        load_error=load_error,
    )



@bp.route("/api/recommend")
def api_recommend():
    """
    JSON API for programmatic access.
    Also logs each call into SearchLog, same as the web form.
    """
    query = (request.args.get("query") or "").strip()
    topk = int(request.args.get("topk", 5))

    if not query:
        return jsonify({"error": "query is required"}), 400

    try:
        t0 = time.perf_counter()
        ensure_models_loaded()
        results = recommend_topk(query, topk)
        latency_ms = int((time.perf_counter() - t0) * 1000)

        top_text = (results[0]["text"][:120] + "…") if results else None

        # Log the API call
        log = SearchLog(
            query=query,
            results_count=len(results or []),
            top_text=top_text,
            latency_ms=latency_ms,
        )
        db.session.add(log)
        db.session.commit()

        return jsonify(results)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
