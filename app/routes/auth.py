"""One shared password. Set on first start, required for every page except /health.

Not used as a Home Assistant add-on, where Home Assistant has already logged the user in.
"""

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app import state
from app.services import settings

bp = Blueprint("auth", __name__)

OPEN_ENDPOINTS = {"auth.login", "auth.setup", "dashboard.health", "static"}
MIN_PASSWORD = 8


def _password_hash() -> str | None:
    with state().db.session() as s:
        return settings.get_value(s, "password_hash")


def set_password(password: str) -> None:
    with state().db.session() as s:
        settings.set_values(s, {"password_hash": generate_password_hash(password)})


@bp.before_app_request
def require_login():
    if not state().cfg.password_required or request.endpoint in OPEN_ENDPOINTS:
        return None
    if _password_hash() is None:
        return redirect(url_for("auth.setup"))
    if not session.get("authenticated"):
        return redirect(url_for("auth.login", next=request.path))
    return None


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    if not state().cfg.password_required:
        return redirect(url_for("dashboard.index"))
    if _password_hash() is not None:
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        password = request.form.get("password", "")
        if len(password) < MIN_PASSWORD:
            flash(f"Use at least {MIN_PASSWORD} characters.", "error")
        elif password != request.form.get("confirm", ""):
            flash("The passwords don't match.", "error")
        else:
            set_password(password)
            session.permanent = True
            session["authenticated"] = True
            return redirect(url_for("dashboard.index"))
    return render_template("setup.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not state().cfg.password_required:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        stored = _password_hash()
        if stored and check_password_hash(stored, request.form.get("password", "")):
            session.permanent = True
            session["authenticated"] = True
            target = request.args.get("next", "")
            # Only redirect to local paths; `next` is relative to the app's URL prefix.
            if target.startswith("/") and not target.startswith("//"):
                return redirect(request.script_root + target)
            return redirect(url_for("dashboard.index"))
        flash("Wrong password.", "error")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
