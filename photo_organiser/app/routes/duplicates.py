from flask import Blueprint, flash, redirect, render_template, url_for
from sqlalchemy import select

from app import state
from app.jobs.runner import RunInProgress
from app.models import MoveHistory

bp = Blueprint("duplicates", __name__)

PAGE_LIMIT = 500


@bp.route("/duplicates")
def index():
    with state().db.session() as s:
        rows = list(
            s.scalars(
                select(MoveHistory)
                .where(MoveHistory.action == "duplicate", MoveHistory.status == "done", MoveHistory.is_main.is_(True))
                .order_by(MoveHistory.id.desc())
                .limit(PAGE_LIMIT)
            )
        )
    return render_template("duplicates.html", rows=rows, limit=PAGE_LIMIT)


@bp.route("/duplicates/<int:row_id>/restore", methods=["POST"])
def restore(row_id: int):
    """Move one duplicate (and its companions) back to the Inbox."""
    with state().db.session() as s:
        row = s.get(MoveHistory, row_id)
        if row is None or row.action != "duplicate" or row.status != "done":
            flash("That duplicate is no longer in Duplicates.", "error")
            return redirect(url_for("duplicates.index"))
        target_run_id, set_key = row.run_id, row.set_key
    try:
        state().runner.start("restore", target_run_id=target_run_id, set_key=set_key, wait=True)
        flash("Moved back to the Inbox.", "info")
    except RunInProgress as e:
        flash(str(e), "error")
    return redirect(url_for("duplicates.index"))
