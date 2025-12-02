# app/models.py
from datetime import datetime
from . import db
from flask_login import UserMixin


# --------------------
# 1. Search Log (your original model)
# --------------------

class SearchLog(db.Model):
    """
    Stores one row per user search for analytics/monitoring.
    """
    __tablename__ = "search_logs"

    id = db.Column(db.Integer, primary_key=True)
    query = db.Column(db.String(300), nullable=False)        # what the user typed
    results_count = db.Column(db.Integer, default=0)         # how many items we showed
    top_text = db.Column(db.Text)                            # short preview of top result (optional)
    latency_ms = db.Column(db.Integer)                       # request latency (ms)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<SearchLog {self.query[:30]}...>"


# --------------------
# 2. Roles
# --------------------

class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)  # "admin", "student", "supervisor"
    description = db.Column(db.String(255))

    users = db.relationship("User", back_populates="role", lazy="dynamic")

    def __repr__(self):
        return f"<Role {self.name}>"


# --------------------
# 3. Users
# --------------------

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)

    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    role = db.relationship("Role", back_populates="users")

    # Optional fields depending on role
    matric_no = db.Column(db.String(30), unique=True)   # for students
    staff_id = db.Column(db.String(30), unique=True)    # for supervisors

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    # Relationships
    supervised_projects = db.relationship(
        "Project",
        back_populates="supervisor",
        foreign_keys="Project.supervisor_id",
        lazy="dynamic",
    )
    projects = db.relationship(
        "Project",
        back_populates="student",
        foreign_keys="Project.student_id",
        lazy="dynamic",
    )

    submissions = db.relationship("Submission", back_populates="user", lazy="dynamic")
    activity_logs = db.relationship("ActivityLog", back_populates="user", lazy="dynamic")

    def __repr__(self):
        return f"<User {self.email}>"


# --------------------
# 4. Projects
# --------------------

class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)

    # e.g. "proposed", "accepted", "ongoing", "completed"
    status = db.Column(db.String(50), default="proposed")

    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    supervisor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    student = db.relationship(
        "User",
        back_populates="projects",
        foreign_keys=[student_id],
    )
    supervisor = db.relationship(
        "User",
        back_populates="supervised_projects",
        foreign_keys=[supervisor_id],
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    submissions = db.relationship("Submission", back_populates="project", lazy="dynamic")
    evaluations = db.relationship("Evaluation", back_populates="project", lazy="dynamic")

    def __repr__(self):
        return f"<Project {self.title}>"


# --------------------
# 5. Submissions (documents / milestones)
# --------------------

class Submission(db.Model):
    __tablename__ = "submissions"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # e.g. "proposal", "chapter1", "final_report", "presentation"
    type = db.Column(db.String(50), nullable=False)

    file_path = db.Column(db.String(255))   # stored path
    original_filename = db.Column(db.String(255))

    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)

    project = db.relationship("Project", back_populates="submissions")
    user = db.relationship("User", back_populates="submissions")

    evaluations = db.relationship("Evaluation", back_populates="submission", lazy="dynamic")

    def __repr__(self):
        return f"<Submission {self.type} - Project {self.project_id}>"


# --------------------
# 6. Evaluations (marks & feedback)
# --------------------

class Evaluation(db.Model):
    __tablename__ = "evaluations"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    submission_id = db.Column(db.Integer, db.ForeignKey("submissions.id"), nullable=True)

    evaluator_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    criterion = db.Column(db.String(100))  # e.g. "content", "presentation"
    score = db.Column(db.Float)
    max_score = db.Column(db.Float, default=100.0)

    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship("Project", back_populates="evaluations")
    submission = db.relationship("Submission", back_populates="evaluations")
    evaluator = db.relationship("User", foreign_keys=[evaluator_id])

    def __repr__(self):
        return f"<Evaluation project={self.project_id} score={self.score}>"


# --------------------
# 7. Activity Log (for admin analytics)
# --------------------

class ActivityLog(db.Model):
    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # High-level description of what happened
    action = db.Column(db.String(100), nullable=False)
    # e.g. "login", "view_page", "create_project", "submit_document"

    details = db.Column(db.Text)  # optional JSON/string
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship("User", back_populates="activity_logs")

    def __repr__(self):
        return f"<ActivityLog {self.action} by {self.user_id} at {self.created_at}>"
    

# --------------------
# 8. User Preferences (for cold-start)
# --------------------

class UserPreference(db.Model):
    __tablename__ = "user_preferences"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        unique=True,
        nullable=False
    )

    # Comma-separated list of topics e.g. "Stress,Anxiety,Sleep"
    topics = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    user = db.relationship(
        "User",
        backref=db.backref("preference", uselist=False)
    )

    def __repr__(self):
        return f"<UserPreference user_id={self.user_id} topics={self.topics}>"

