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
from .models import SearchLog, User, Role, UserPreference
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

# ---------------------------
# Recommender (public)
# ---------------------------

@bp.route("/recommend", methods=["GET", "POST"])
def recommend_page():
    """
    GET  -> just show the form.
    POST -> run the recommender AND log the search into the database.
    Uses user preferences (if logged in) to help with cold start.
    """
    load_error = None
    results = None
    query = ""
    topk = 5
    used_prefs_only = False  # flag for template message

    if request.method == "POST":
        # Read form inputs safely
        query = (request.form.get("query") or "").strip()
        try:
            topk = int(request.form.get("topk") or 5)
        except ValueError:
            topk = 5  # fallback

        # Build effective query using preferences (for cold-start)
        effective_query = query

        pref_topics = ""
        if current_user.is_authenticated and getattr(current_user, "preference", None):
            pref_topics = current_user.preference.topics or ""

        # If user has preferences, weave them into the query
        if pref_topics:
            pref_terms = pref_topics.replace(",", " ")
            if effective_query:
                # boost user preferences on top of their explicit query
                effective_query = f"{effective_query} {pref_terms}"
            else:
                # cold-start: no query, just use preferences
                effective_query = pref_terms
                used_prefs_only = True

        if effective_query:
            try:
                # Measure how long the recommendation takes
                t0 = time.perf_counter()

                # Make sure dataset/model are ready
                ensure_models_loaded()

                # Get top-k recommendations
                results = recommend_topk(effective_query, topk)

                latency_ms = int((time.perf_counter() - t0) * 1000)

                # Short preview of the top result (for analytics)
                top_text = (results[0]["text"][:120] + "…") if results else None

                # Log only the original query text (what user actually typed)
                log = SearchLog(
                    query=query if query else f"[prefs:{pref_topics}]",
                    results_count=len(results or []),
                    top_text=top_text,
                    latency_ms=latency_ms,
                )
                db.session.add(log)
                db.session.commit()  # actually write to the DB

            except Exception as e:
                # Any error (e.g. dataset missing) -> show friendly message
                load_error = str(e)
        else:
            load_error = "Please enter a query or set your interests in the Profile page."

    return render_template(
        "results.html",
        query=query,
        results=results,
        topk=topk,
        load_error=load_error,
        used_prefs_only=used_prefs_only,
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


# ---------------------------
# User profile & password
# ---------------------------

@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """
    Show and update basic user profile info + preferences.
    Preferences are stored in UserPreference (one row per user).
    """
    # Ensure a preference row exists for this user
    pref = UserPreference.query.filter_by(user_id=current_user.id).first()
    if not pref:
        pref = UserPreference(user_id=current_user.id, topics="")
        db.session.add(pref)
        db.session.commit()

    # Define the available topics (you can tweak these labels)
    all_topics = [
        "Stress",
        "Anxiety",
        "Sadness / Depression",
        "Relationships",
        "Sleep",
        "Work / Study Pressure",
        "Self-esteem & Confidence",
        "Motivation / Productivity",
    ]

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()

        if not name:
            flash("Name cannot be empty.", "danger")
            return redirect(url_for("main.profile"))

        # Update name
        current_user.full_name = name

        # Update preferences (checkboxes)
        selected_topics = request.form.getlist("topics")  # list of strings
        pref.topics = ",".join(selected_topics)

        db.session.commit()
        flash("Profile & preferences updated.", "success")
        return redirect(url_for("main.profile"))

    # For GET: prepare which topics are already selected
    selected_topics = (
        [t for t in (pref.topics or "").split(",") if t.strip()]
        if pref and pref.topics
        else []
    )

    return render_template(
        "profile.html",
        all_topics=all_topics,
        selected_topics=selected_topics,
    )



@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    """
    Allow a logged-in user to change their password.
    """
    if request.method == "POST":
        current_pw = request.form.get("current_password") or ""
        new_pw = request.form.get("new_password") or ""
        confirm_pw = request.form.get("confirm_password") or ""

        # 1. Check current password
        if not check_password_hash(current_user.password_hash, current_pw):
            flash("Current password is incorrect.", "danger")
            return redirect(url_for("main.change_password"))

        # 2. Check new password match
        if new_pw != confirm_pw:
            flash("New passwords do not match.", "danger")
            return redirect(url_for("main.change_password"))

        # 3. Basic length check
        if len(new_pw) < 6:
            flash("New password must be at least 6 characters.", "danger")
            return redirect(url_for("main.change_password"))

        # 4. Save new password
        current_user.password_hash = generate_password_hash(new_pw)
        db.session.commit()

        flash("Password updated successfully.", "success")
        return redirect(url_for("main.profile"))

    return render_template("change_password.html")
