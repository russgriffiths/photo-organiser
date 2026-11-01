from flask import Blueprint, abort, render_template
from sqlalchemy import select

from app import state
from app.jobs.runner import undoable_run
from app.models import MoveHistory, Run

bp = Blueprint("history", __name__)


@bp.route("/history")
def index():
    with state().db.session() as s:
        runs = list(s.scalars(select(Run).order_by(Run.started_at.desc()).limit(100)))
        undoable = {r.run_id for r in runs if r.kind == "organise" and undoable_run(s, r.run_id)}
    return render_template("history.html", runs=runs, undoable=undoable)


@bp.route("/history/<run_id>")
def detail(run_id: str):
    with state().db.session() as s:
        run = s.scalar(select(Run).where(Run.run_id == run_id))
        if run is None:
            abort(404)
        rows = list(
            s.scalars(select(MoveHistory).where(MoveHistory.run_id == run_id).order_by(MoveHistory.id).limit(2000))
        )
        can_undo = run.kind == "organise" and undoable_run(s, run_id) is not None
    return render_template("run_detail.html", run=run, rows=rows, can_undo=can_undo)
