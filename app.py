"""
SIGNRA BACKEND — app.py
========================
Full backend with auth, contracts, AI generation.
Admin email gets unlimited everything for free.
"""

import os
import datetime
import jwt
from functools import wraps
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import requests

app = Flask(__name__)
CORS(app, supports_credentials=True, origins="*")

SECRET_KEY   = os.environ.get("SECRET_KEY", "change-this-secret-key-please")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL   = "llama-3.3-70b-versatile"
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")

# ── ADMIN ─────────────────────────────────────────────────
# Any email listed here gets unlimited everything for free.
ADMIN_EMAILS = {
    "omar050411@gmail.com",   # Omar — full admin
}

def is_admin(email):
    return (email or "").strip().lower() in ADMIN_EMAILS

# ── DATABASE ──────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///signra.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine      = create_engine(DATABASE_URL, echo=False)
Base        = declarative_base()
SessionLocal = sessionmaker(bind=engine)


class User(Base):
    __tablename__ = "users"
    id            = Column(Integer, primary_key=True)
    name          = Column(String(120))
    email         = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(300))
    plan          = Column(String(20), default="free")
    created_at    = Column(DateTime, default=datetime.datetime.utcnow)
    contracts     = relationship("Contract", back_populates="owner")


class Contract(Base):
    __tablename__ = "contracts"
    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id"))
    title      = Column(String(200))
    type       = Column(String(80))
    content    = Column(Text)
    status     = Column(String(20), default="done")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    owner      = relationship("User", back_populates="contracts")


class Event(Base):
    __tablename__ = "events"
    id         = Column(Integer, primary_key=True)
    type       = Column(String(40))   # 'pageview', 'contract_generated', 'pdf_tool'
    name       = Column(String(120))  # page name / contract type / tool name
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Feedback(Base):
    __tablename__ = "feedback"
    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=True)
    name       = Column(String(120))
    email      = Column(String(120))
    category   = Column(String(60))
    message    = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


Base.metadata.create_all(engine)


# ── HELPERS ───────────────────────────────────────────────
def make_token(user_id):
    payload = {
        "user_id": user_id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=30),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Not signed in"}), 401
        token = auth.split(" ", 1)[1]
        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            request.user_id = data["user_id"]
        except Exception:
            return jsonify({"error": "Session expired, please sign in again"}), 401
        return f(*args, **kwargs)
    return wrapper


def get_user_plan(user):
    """Admin email always gets 'admin' plan regardless of DB value."""
    if is_admin(user.email):
        return "admin"
    return user.plan


def optional_user_id():
    """Returns user_id from token if present and valid, else None. Never raises."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        data = jwt.decode(auth.split(" ", 1)[1], SECRET_KEY, algorithms=["HS256"])
        return data.get("user_id")
    except Exception:
        return None


def log_event(event_type, name, user_id=None):
    db = SessionLocal()
    try:
        db.add(Event(type=event_type, name=(name or "")[:120], user_id=user_id))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


# ── ROUTES ────────────────────────────────────────────────
@app.route("/")
def home():
    return jsonify({"message": "Signra backend is running!", "status": "ok"})


@app.route("/api/signup", methods=["POST"])
def signup():
    data     = request.get_json()
    name     = (data.get("name") or "").strip()
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    db = SessionLocal()
    try:
        if db.query(User).filter_by(email=email).first():
            return jsonify({"error": "An account with this email already exists"}), 400

        # Admin email automatically gets the 'admin' plan in the DB too
        plan = "admin" if is_admin(email) else "free"

        user = User(
            name          = name or email.split("@")[0],
            email         = email,
            password_hash = generate_password_hash(password),
            plan          = plan,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        token = make_token(user.id)
        return jsonify({
            "token": token,
            "user": {
                "id":    user.id,
                "name":  user.name,
                "email": user.email,
                "plan":  get_user_plan(user),
                "admin": is_admin(user.email),
            },
        })
    finally:
        db.close()


@app.route("/api/signin", methods=["POST"])
def signin():
    data     = request.get_json()
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            return jsonify({"error": "Wrong email or password"}), 401

        # Upgrade admin in DB if not already set
        if is_admin(user.email) and user.plan != "admin":
            user.plan = "admin"
            db.commit()

        token = make_token(user.id)
        return jsonify({
            "token": token,
            "user": {
                "id":    user.id,
                "name":  user.name,
                "email": user.email,
                "plan":  get_user_plan(user),
                "admin": is_admin(user.email),
            },
        })
    finally:
        db.close()


@app.route("/api/google-auth", methods=["POST"])
def google_auth():
    """Sign in or sign up using a Google account."""
    data = request.get_json()
    credential = data.get("credential", "")
    if not credential:
        return jsonify({"error": "Missing Google credential"}), 400

    # Verify the token with Google's servers
    try:
        r = requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": credential},
            timeout=10,
        )
        r.raise_for_status()
        info = r.json()
    except Exception:
        return jsonify({"error": "Could not verify Google account"}), 400

    if GOOGLE_CLIENT_ID and info.get("aud") != GOOGLE_CLIENT_ID:
        return jsonify({"error": "Google login not configured correctly"}), 400

    email = (info.get("email") or "").strip().lower()
    name  = info.get("name") or email.split("@")[0]
    if not email:
        return jsonify({"error": "Google account has no email"}), 400

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email=email).first()
        if not user:
            plan = "admin" if is_admin(email) else "free"
            user = User(name=name, email=email, password_hash="", plan=plan)
            db.add(user)
            db.commit()
            db.refresh(user)
        elif is_admin(email) and user.plan != "admin":
            user.plan = "admin"
            db.commit()

        token = make_token(user.id)
        return jsonify({
            "token": token,
            "user": {
                "id":    user.id,
                "name":  user.name,
                "email": user.email,
                "plan":  get_user_plan(user),
                "admin": is_admin(user.email),
            },
        })
    finally:
        db.close()


@app.route("/api/me", methods=["GET"])
@login_required
def me():
    db = SessionLocal()
    try:
        user = db.get(User, request.user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        done_count  = db.query(Contract).filter_by(user_id=user.id, status="done").count()
        draft_count = db.query(Contract).filter_by(user_id=user.id, status="draft").count()
        return jsonify({
            "user": {
                "id":    user.id,
                "name":  user.name,
                "email": user.email,
                "plan":  get_user_plan(user),
                "admin": is_admin(user.email),
            },
            "stats": {"contracts": done_count, "drafts": draft_count},
        })
    finally:
        db.close()


@app.route("/api/track", methods=["POST"])
def track_event():
    """Fire-and-forget analytics: pageviews, pdf tool usage, etc."""
    data = request.get_json(silent=True) or {}
    event_type = data.get("type", "pageview")
    name = data.get("name", "")
    if event_type not in ("pageview", "pdf_tool"):
        return jsonify({"ok": False}), 400
    log_event(event_type, name, optional_user_id())
    return jsonify({"ok": True})


@app.route("/api/feedback", methods=["POST"])
def submit_feedback():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Message is required"}), 400
    db = SessionLocal()
    try:
        db.add(Feedback(
            user_id=optional_user_id(),
            name=(data.get("name") or "")[:120],
            email=(data.get("email") or "")[:120],
            category=(data.get("category") or "General")[:60],
            message=message,
        ))
        db.commit()
    finally:
        db.close()
    return jsonify({"ok": True})


@app.route("/api/generate", methods=["POST"])
@login_required
def generate():
    data = request.get_json()

    db = SessionLocal()
    try:
        user = db.get(User, request.user_id)
        plan = get_user_plan(user)

        # Free users: max 1 contract. Admin/Pro/Business: unlimited.
        if plan == "free":
            done = db.query(Contract).filter_by(user_id=user.id, status="done").count()
            if done >= 1:
                return jsonify({
                    "error": "Free plan limit reached. Upgrade to Pro for unlimited contracts."
                }), 403
    finally:
        db.close()

    contract_type = data.get('type', 'Service Agreement')

    # Build type-specific details block
    extra_details = ""
    if contract_type == "Employment Contract":
        extra_details = f"""Job Title / Position: {data.get('role','')}
Employment Type: {data.get('employmentType','Full-time')}
Probation Period: {data.get('probation','') or 'Not specified'}
Salary / Wage: {data.get('currency','USD')} {data.get('price','')}
Pay Frequency: {data.get('payFrequency','')}"""
    elif contract_type == "NDA":
        extra_details = f"""NDA Type: {data.get('ndaType','Mutual')}
Confidentiality Duration: {data.get('duration','')}
(This is an NDA — do not include payment/price sections unless explicitly mentioned in notes.)"""
    elif contract_type == "Freelance / Contractor":
        extra_details = f"""Project Fee: {data.get('currency','USD')} {data.get('price','')} — {data.get('paymentTerms','')}
Revisions Included: {data.get('revisions','') or 'Not specified'}
Intellectual Property: {data.get('ip','Transfers to Client on final payment')}"""
    else:  # Service Agreement / Custom
        extra_details = f"""Payment: {data.get('currency','USD')} {data.get('price','')} — {data.get('paymentTerms','')}
Service Frequency: {data.get('frequency','One-time') or 'One-time'}"""

    if plan == "free":
        disclaimer_instruction = (
            'a final line that reads exactly: "Generated with Signra \u2014 signra.net. '
            'This document does not constitute legal advice and should be reviewed by a '
            'qualified professional before use."'
        )
    else:
        disclaimer_instruction = (
            'a short, brand-neutral disclaimer noting that this document does not constitute '
            'legal advice and should be reviewed by a qualified professional before use. '
            'Do NOT mention Signra, signra.net, or any generator/tool name anywhere in the document.'
        )

    prompt = f"""You are a professional contract writer for US small businesses.
Write a complete, professional {contract_type} contract.

Style: {data.get('style','Formal')}
Party A (Contractor/Employer): {data.get('partyA','')} — {data.get('locationA','')}
Party B (Client/Employee): {data.get('partyB','')} — {data.get('locationB','')}
Scope of work / Job description: {data.get('scope','')}
{extra_details}
Additional notes: {data.get('notes','')}

Write a complete, numbered contract with all standard clauses appropriate for a {contract_type},
signature blocks at the end, and {disclaimer_instruction}
Use the type-specific details above to fill in the relevant sections accurately."""

    if not GROQ_API_KEY:
        return jsonify({"error": "AI key not configured on the server"}), 500

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "model":    GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4,
            },
            timeout=60,
        )
        r.raise_for_status()
        contract_text = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return jsonify({"error": f"AI generation failed: {str(e)}"}), 500

    log_event("contract_generated", contract_type, request.user_id)
    return jsonify({"contract": contract_text})


@app.route("/api/contracts", methods=["GET"])
@login_required
def list_contracts():
    db = SessionLocal()
    try:
        rows = (db.query(Contract)
                  .filter_by(user_id=request.user_id)
                  .order_by(Contract.created_at.desc())
                  .all())
        return jsonify({"contracts": [
            {
                "id":         c.id,
                "title":      c.title,
                "type":       c.type,
                "status":     c.status,
                "content":    c.content,
                "created_at": c.created_at.strftime("%d %b %Y"),
            }
            for c in rows
        ]})
    finally:
        db.close()


@app.route("/api/contracts", methods=["POST"])
@login_required
def save_contract():
    data = request.get_json()
    db   = SessionLocal()
    try:
        c = Contract(
            user_id = request.user_id,
            title   = data.get("title", "Untitled Contract"),
            type    = data.get("type",  "Contract"),
            content = data.get("content", ""),
            status  = data.get("status",  "done"),
        )
        db.add(c)
        db.commit()
        db.refresh(c)
        return jsonify({"id": c.id, "message": "Saved"})
    finally:
        db.close()


@app.route("/api/contracts/<int:cid>", methods=["DELETE"])
@login_required
def delete_contract(cid):
    db = SessionLocal()
    try:
        c = db.query(Contract).filter_by(id=cid, user_id=request.user_id).first()
        if not c:
            return jsonify({"error": "Not found"}), 404
        db.delete(c)
        db.commit()
        return jsonify({"message": "Deleted"})
    finally:
        db.close()


# ── ADMIN ROUTES ──────────────────────────────────────────
@app.route("/api/admin/users", methods=["GET"])
@login_required
def admin_list_users():
    """Only admin can see all users."""
    db = SessionLocal()
    try:
        me = db.get(User, request.user_id)
        if not is_admin(me.email):
            return jsonify({"error": "Admin only"}), 403
        users = db.query(User).order_by(User.created_at.desc()).all()
        return jsonify({"users": [
            {
                "id":         u.id,
                "name":       u.name,
                "email":      u.email,
                "plan":       get_user_plan(u),
                "created_at": u.created_at.strftime("%d %b %Y"),
                "contracts":  db.query(Contract).filter_by(user_id=u.id).count(),
            }
            for u in users
        ]})
    finally:
        db.close()


@app.route("/api/admin/set-plan", methods=["POST"])
@login_required
def admin_set_plan():
    """Admin can upgrade or downgrade any user's plan."""
    db = SessionLocal()
    try:
        me = db.get(User, request.user_id)
        if not is_admin(me.email):
            return jsonify({"error": "Admin only"}), 403
        data  = request.get_json()
        email = (data.get("email") or "").strip().lower()
        plan  = data.get("plan", "free")
        user  = db.query(User).filter_by(email=email).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        user.plan = plan
        db.commit()
        return jsonify({"message": f"{email} is now on the {plan} plan"})
    finally:
        db.close()


@app.route("/api/admin/stats", methods=["GET"])
@login_required
def admin_stats():
    db = SessionLocal()
    try:
        me = db.get(User, request.user_id)
        if not is_admin(me.email):
            return jsonify({"error": "Admin only"}), 403

        total_users = db.query(User).count()
        pro_users   = db.query(User).filter(User.plan.in_(["pro", "admin", "business"])).count()
        free_users  = total_users - pro_users

        total_contracts = db.query(Contract).filter_by(status="done").count()
        total_drafts     = db.query(Contract).filter_by(status="draft").count()

        contracts_by_type = dict(
            db.query(Event.name, func.count(Event.id))
              .filter(Event.type == "contract_generated")
              .group_by(Event.name)
              .order_by(func.count(Event.id).desc())
              .all()
        )

        pageviews_by_page = dict(
            db.query(Event.name, func.count(Event.id))
              .filter(Event.type == "pageview")
              .group_by(Event.name)
              .order_by(func.count(Event.id).desc())
              .all()
        )
        total_pageviews = sum(pageviews_by_page.values())

        pdf_tool_usage = dict(
            db.query(Event.name, func.count(Event.id))
              .filter(Event.type == "pdf_tool")
              .group_by(Event.name)
              .order_by(func.count(Event.id).desc())
              .all()
        )

        feedback_count = db.query(Feedback).count()

        # Signups in the last 30 days, grouped by date
        thirty_days_ago = datetime.datetime.utcnow() - datetime.timedelta(days=30)
        signups_recent = (
            db.query(func.date(User.created_at), func.count(User.id))
              .filter(User.created_at >= thirty_days_ago)
              .group_by(func.date(User.created_at))
              .order_by(func.date(User.created_at))
              .all()
        )
        signups_by_day = {str(d): n for d, n in signups_recent}

        return jsonify({
            "users": {
                "total": total_users,
                "free": free_users,
                "pro": pro_users,
            },
            "contracts": {
                "total_done": total_contracts,
                "total_drafts": total_drafts,
                "by_type": contracts_by_type,
            },
            "pageviews": {
                "total": total_pageviews,
                "by_page": pageviews_by_page,
            },
            "pdf_tools": {
                "by_tool": pdf_tool_usage,
                "total": sum(pdf_tool_usage.values()),
            },
            "feedback_count": feedback_count,
            "signups_by_day": signups_by_day,
        })
    finally:
        db.close()


@app.route("/api/admin/feedback", methods=["GET"])
@login_required
def admin_feedback():
    db = SessionLocal()
    try:
        me = db.get(User, request.user_id)
        if not is_admin(me.email):
            return jsonify({"error": "Admin only"}), 403
        rows = db.query(Feedback).order_by(Feedback.created_at.desc()).limit(200).all()
        return jsonify({"feedback": [
            {
                "id": f.id,
                "name": f.name,
                "email": f.email,
                "category": f.category,
                "message": f.message,
                "created_at": f.created_at.strftime("%d %b %Y %H:%M"),
            }
            for f in rows
        ]})
    finally:
        db.close()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
