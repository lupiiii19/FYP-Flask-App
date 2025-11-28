# app/routes.py
import time
from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    flash,
    abort,
)
from flask_login import (
    login_user,
    logout_user,
    login_required,
    current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash

from .services.recommender import ensure_models_loaded, recommend_topk
from .models import SearchLog, User, Role
from . import db
from sqlalchemy import func, desc

bp = Blueprint("main", __name__)


# ---------------------------
# Public pages
# ---------------------------

@bp.route("/")
def index():
    # Home stays lightweight—no model load here
    return render_template("index.html")


# ---------------------------
# Authentication
# ---------------------------

@bp.route("/register", methods=["GET", "POST"])
def register():
    """
    Simple user registration.
    Creates a normal 'user' account (not admin).
    """
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        name = (request.form.get("name") or "").strip()
        password = request.form.get("password") or ""

        if not email or not name or not password:
            flash("Please fill in all fields.", "danger")
            return redirect(url_for("main.register"))

        # Check existing email
        if User.query.filter_by(email=email).first():
            flash("Email is already registered.", "danger")
            return redirect(url_for("main.register"))

        # Get or create 'user' role
        user_role = Role.query.filter_by(name="user").first()
        if not user_role:
            user_role = Role(name="user", description="Normal user")
            db.session.add(user_role)
            db.session.commit()

        new_user = User(
            email=email,
            full_name=name,
            password_hash=generate_password_hash(password),
            role=user_role,
        )
        db.session.add(new_user)
        db.session.commit()

        flash("Account created. Please log in.", "success")
        return redirect(url_for("main.login"))

    return render_template("register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    """
    Log a user in.
    """
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash("Invalid email or password.", "danger")
            return redirect(url_for("main.login"))

        login_user(user)
        flash("Logged in successfully.", "success")
        return redirect(url_for("main.index"))

    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    """
    Log the current user out.
    """
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("main.index"))


# Optional helper route to create the first admin account
@bp.route("/init-admin")
def init_admin():
    """
    ONE-TIME helper to create an admin account.
    Visit this route once, then remove or disable it.

    Admin credentials created:
        email: admin@example.com
        password: changeme123
    """
    admin_email = "admin@example.com"

    # If admin already exists, don't create another
    existing = User.query.filter_by(email=admin_email).first()
    if existing:
        return "Admin already exists."

    # Get or create 'admin' role
    admin_role = Role.query.filter_by(name="admin").first()
    if not admin_role:
        admin_role = Role(name="admin", description="Admin user")
        db.session.add(admin_role)
        db.session.commit()

    admin = User(
        email=admin_email,
        full_name="Admin",
        password_hash=generate_password_hash("changeme123"),
        role=admin_role,
    )
    db.session.add(admin)
    db.session.commit()

    return "Admin created: admin@example.com / changeme123"


# ---------------------------
# Recommender (public)
# ---------------------------

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
    try:
        topk = int(request.args.get("topk", 5))
    except ValueError:
        topk = 5

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


# ---------------------------
# Admin analytics (protected)
# ---------------------------

@bp.route("/admin/analytics")
@login_required
def analytics():
    """
    Simple analytics page.
    Shows totals, average latency, top queries, and recent logs.
    Only accessible to admin users.
    """
    # Check role: must be admin
    if not current_user.role or current_user.role.name != "admin":
        abort(403)

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
