"""Writing plans to move_history, and reading a dry run's plan back."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Config
from app.models import MoveHistory, Run
from app.services.planner import PlannedFile, PlannedSet


def record_set(
    session: Session,
    cfg: Config,
    run_id: str,
    ps: PlannedSet,
    status: str,
    error: str | None = None,
) -> None:
    now = datetime.now()
    for f in ps.files:
        session.add(
            MoveHistory(
                run_id=run_id,
                set_key=ps.key,
                action=ps.action,
                is_main=f.is_main,
                old_path=cfg.rel(f.source),
                new_path=cfg.rel(f.dest) if f.dest else None,
                hash=ps.hash if f.is_main else None,
                size=f.size,
                mtime=f.mtime,
                photo_date=ps.photo_date,
                date_source=ps.date_source,
                matched_path=ps.matched,
                status=status,
                error=error or (ps.reason if ps.action in ("skip", "reject") else None),
                action_time=now,
            )
        )


def count_into(run: Run, ps: PlannedSet) -> None:
    if ps.action == "move":
        run.files_moved += 1
    elif ps.action == "duplicate":
        run.duplicates += 1
    elif ps.action == "reject":
        run.rejected += 1


def plan_from_dry_run(session: Session, cfg: Config, run_id: str) -> list[PlannedSet]:
    """Rebuild the plan a dry run recorded, so Organise applies exactly what was previewed."""
    rows = session.scalars(
        select(MoveHistory).where(MoveHistory.run_id == run_id).order_by(MoveHistory.id)
    )
    sets: dict[str, PlannedSet] = {}
    for r in rows:
        ps = sets.get(r.set_key)
        if ps is None:
            ps = sets[r.set_key] = PlannedSet(
                r.set_key, r.action, [], r.photo_date, r.date_source, r.hash, r.matched_path, r.error
            )
        ps.files.append(
            PlannedFile(
                cfg.abs(r.old_path),
                cfg.abs(r.new_path) if r.new_path else None,
                r.size or 0,
                r.mtime or 0.0,
                r.is_main,
            )
        )
    for ps in sets.values():
        ps.files.sort(key=lambda f: not f.is_main)
    return list(sets.values())
