import re

from flask import Blueprint, flash, redirect, render_template, request, url_for
from werkzeug.security import check_password_hash

from app import state
from app.routes.auth import MIN_PASSWORD, set_password
from app.services import settings as settings_service
from app.services.metadata import DATE_SOURCES

bp = Blueprint("settings", __name__)

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@bp.route("/settings", methods=["GET", "POST"])
def index():
    st = state()
    if request.method == "POST":
        form = request.form
        errors = []
        schedule_time = form.get("schedule_time", "")
        if not TIME_RE.match(schedule_time):
            errors.append("Schedule time must be HH:MM.")
        duplicate_handling = form.get("duplicate_handling")
        if duplicate_handling not in ("move", "skip"):
            errors.append("Choose how to handle duplicates.")
        folder_layout = form.get("folder_layout")
        if folder_layout not in settings_service.FOLDER_LAYOUTS:
            errors.append("Choose a folder structure.")
        # Ticked sources arrive in the order they are listed on the page.
        date_sources = settings_service.parse_date_sources(",".join(form.getlist("date_sources")))
        if not date_sources:
            errors.append("Tick at least one way of finding the date.")
        try:
            stable = int(form.get("stable_minutes", ""))
            if not 0 <= stable <= 1440:
                raise ValueError
        except ValueError:
            errors.append("Wait time must be 0 to 1440 minutes.")
            stable = 5

        new_password = form.get("new_password", "") if st.cfg.password_required else ""
        if new_password:
            with st.db.session() as s:
                current_ok = check_password_hash(
                    settings_service.get_value(s, "password_hash") or "", form.get("current_password", "")
                )
            if not current_ok:
                errors.append("Current password is wrong.")
            elif len(new_password) < MIN_PASSWORD:
                errors.append(f"New password needs at least {MIN_PASSWORD} characters.")

        if errors:
            for e in errors:
                flash(e, "error")
        else:
            with st.db.session() as s:
                settings_service.set_values(
                    s,
                    {
                        "schedule_enabled": "1" if form.get("schedule_enabled") else "0",
                        "schedule_time": schedule_time,
                        "duplicate_handling": duplicate_handling,
                        "folder_layout": folder_layout,
                        "date_sources": ",".join(date_sources),
                        "stable_minutes": str(stable),
                    },
                )
            if new_password:
                set_password(new_password)
            if st.scheduler:
                st.scheduler.apply_settings()
            flash("Settings saved.", "info")
            return redirect(url_for("settings.index"))

    with st.db.session() as s:
        current = settings_service.load(s)
    # Ticked sources first, in their order, then the unticked ones.
    source_rows = [(key, DATE_SOURCES[key], True) for key in current.date_sources]
    source_rows += [(key, label, False) for key, label in DATE_SOURCES.items() if key not in current.date_sources]
    return render_template(
        "settings.html",
        s=current,
        cfg=st.cfg,
        source_rows=source_rows,
        layouts=settings_service.FOLDER_LAYOUTS,
    )
