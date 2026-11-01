from pathlib import PurePosixPath

from flask import Blueprint, render_template, request
from sqlalchemy import select

from app import state
from app.jobs.runner import usable_preview
from app.models import MoveHistory, Run

bp = Blueprint("preview", __name__)

PAGE_LIMIT = 1000

FILTERS = {
    "all": lambda r: True,
    "move": lambda r: r.action == "move",
    "duplicate": lambda r: r.action == "duplicate",
    "reject": lambda r: r.action == "reject",
    "skip": lambda r: r.action == "skip",
    "low": lambda r: r.date_source == "mtime",
    "renamed": lambda r: r.new_path is not None
    and PurePosixPath(r.new_path).name != PurePosixPath(r.old_path).name,
}


@bp.route("/preview")
def index():
    selected = request.args.get("filter", "all")
    keep = FILTERS.get(selected, FILTERS["all"])
    with state().db.session() as s:
        run = s.scalar(
            select(Run).where(Run.kind == "organise", Run.dry_run.is_(True)).order_by(Run.started_at.desc())
        )
        fresh = usable_preview(s)
        rows, companions = [], {}
        if run:
            all_rows = list(
                s.scalars(select(MoveHistory).where(MoveHistory.run_id == run.run_id).order_by(MoveHistory.id))
            )
            for r in all_rows:
                if not r.is_main:
                    companions.setdefault(r.set_key, []).append(PurePosixPath(r.old_path).suffix)
            rows = [r for r in all_rows if r.is_main and keep(r)]
    return render_template(
        "preview.html",
        run=run,
        can_apply=fresh is not None and run is not None and fresh.run_id == run.run_id,
        rows=rows[:PAGE_LIMIT],
        total=len(rows),
        limit=PAGE_LIMIT,
        companions=companions,
        selected=selected,
        filters=list(FILTERS),
    )
