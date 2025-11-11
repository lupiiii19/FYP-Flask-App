# app/routes.py
import time
from flask import Blueprint, render_template, request, jsonify
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
    # Try loading model/data only when needed
    load_error = None
    try:
        ensure_models_loaded()
    except Exception as e:
        load_error = str(e)

    results, query, topk = None, "", 5

    if request.method == "POST" and load_error is None:
        query = (request.form.get("query") or "").strip()
        try:
            topk = int(request.form.get("topk") or 5)
        except ValueError:
            topk = 5

        if query:
            t0 = time.perf_counter()
            results = recommend_topk(query, topk)
            latency_ms = int((time.perf_counter() - t0) * 1000)

            # Prepare a short preview for analytics (first 120 chars)
            top_text = (results[0]["text"][:120] + "…") if results else None

            # Write a SearchLog row
            log = SearchLog(
                query=query,
                results_count=len(results or []),
                top_text=top_text,
                latency_ms=latency_ms,
            )
            db.session.add(log)
            db.session.commit()

    return render_template(
        "results.html",
        query=query,
        results=results,
        topk=topk,
        load_error=load_error
    )

@bp.route("/api/recommend")
def api_recommend():
    # JSON API mirrors the UI behavior
    try:
        ensure_models_loaded()
    except Exception as e:
        return jsonify({"error": f"Model not loaded: {e}"}), 500

    query = (request.args.get("query") or "").strip()
    topk = int(request.args.get("topk", 5))
    if not query:
        return jsonify({"error": "query is required"}), 400

    t0 = time.perf_counter()
    results = recommend_topk(query, topk)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    # Log the API call too
    top_text = (results[0]["text"][:120] + "…") if results else None
    db.session.add(SearchLog(query=query, results_count=len(results), top_text=top_text, latency_ms=latency_ms))
    db.session.commit()

    return jsonify(results)

@bp.route("/admin/analytics")
def analytics():
    """
    Very simple analytics page (no auth yet—OK for local dev):
      - totals
      - recent searches
      - top queries
      - average latency
    """
    # Totals
    total = db.session.query(func.count(SearchLog.id)).scalar()
    avg_latency = db.session.query(func.avg(SearchLog.latency_ms)).scalar() or 0

    # Top queries (grouped)
    top_queries = (
        db.session.query(SearchLog.query, func.count(SearchLog.id).label("n"))
        .group_by(SearchLog.query)
        .order_by(desc("n"))
        .limit(10)
        .all()
    )

    # Recent 20
    recent = (
        db.session.query(SearchLog)
        .order_by(desc(SearchLog.created_at))
        .limit(20)
        .all()
    )

    return render_template(
        "analytics.html",
        total=total,
        avg_latency=int(avg_latency),
        top_queries=top_queries,
        recent=recent
    )
