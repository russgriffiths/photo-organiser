from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import select

from app import state
from app.jobs.runner import RunInProgress, undoable_run, usable_preview
from app.models import Run
from app.services import settings
from app.services.index import photo_count

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    st = state()
    with st.db.session() as s:
        last_run = s.scalar(select(Run).where(Run.kind == "organise").order_by(Run.started_at.desc()))
        stats = {
            "inbox": settings.get_value(s, "stat_inbox_count"),
            "organised": photo_count(s, st.cfg.organised_dir),
            "duplicates": photo_count(s, st.cfg.duplicates_dir),
            "rejected": photo_count(s, st.cfg.rejected_dir),
        }
        preview = usable_preview(s)
        undoable = undoable_run(s)
        indexed = s.scalar(select(Run).where(Run.kind == "index", Run.status == "done"))
    return render_template(
        "dashboard.html",
        stats=stats,
        last_run=last_run,
        preview=preview,
        undoable=undoable,
        never_indexed=indexed is None,
        next_run=st.scheduler.next_organise() if st.scheduler else None,
    )


def _start(kind: str, **kwargs):
    try:
        run_id = state().runner.start(kind, trigger="manual", **kwargs)
        flash(f"Started run {run_id}.", "info")
    except RunInProgress as e:
        flash(str(e), "error")
    return redirect(url_for("dashboard.index"))


@bp.route("/run/dry-run", methods=["POST"])
def dry_run():
    return _start("organise", dry_run=True)


@bp.route("/run/organise", methods=["POST"])
def organise():
    with state().db.session() as s:
        preview = usable_preview(s)
    # Apply exactly what was previewed when there is a fresh preview.
    return _start("organise", from_preview=preview.run_id if preview else None)


@bp.route("/run/undo", methods=["POST"])
def undo():
    with state().db.session() as s:
        run = undoable_run(s, request.form.get("run_id") or None)
    if run is None:
        flash("Nothing to undo.", "error")
        return redirect(url_for("dashboard.index"))
    return _start("undo", target_run_id=run.run_id)


@bp.route("/run/index", methods=["POST"])
def rebuild_index():
    return _start("index")


@bp.route("/run/cancel", methods=["POST"])
def cancel():
    state().runner.cancel()
    flash("Cancelling: the run stops after the current batch.", "info")
    return redirect(url_for("dashboard.index"))


@bp.route("/api/status")
def status():
    runner = state().runner
    return jsonify(busy=runner.busy, progress=runner.progress)


@bp.route("/health")
def health():
    inbox = state().cfg.inbox
    ok = inbox.is_dir()
    return jsonify(ok=ok, inbox=str(inbox)), 200 if ok else 503
