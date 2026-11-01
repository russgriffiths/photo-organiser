"""Moves files from a run back to where they came from."""

import logging
import threading
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Config
from app.models import MoveHistory, Run
from app.services.folders import prune_empty_dirs
from app.services.index import LibraryIndex, same_mtime
from app.services.mover import move_file

log = logging.getLogger(__name__)

REVERSIBLE = ("move", "duplicate", "reject")


def undo(
    cfg: Config,
    session: Session,
    target_run_id: str,
    record_run: Run,
    index: LibraryIndex,
    set_key: str | None = None,
    cancel: threading.Event | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    """Reverse a run's moves, newest first, one photo set at a time.

    A set is moved back only if every file is still at its destination,
    unchanged, and nothing occupies its original path. Otherwise it is
    skipped and reported. Pass set_key to restore a single set.
    """
    q = select(MoveHistory).where(
        MoveHistory.run_id == target_run_id,
        MoveHistory.status == "done",
        MoveHistory.action.in_(REVERSIBLE),
    )
    if set_key is not None:
        q = q.where(MoveHistory.set_key == set_key)
    rows = list(session.scalars(q.order_by(MoveHistory.id.desc())))

    sets: dict[str, list[MoveHistory]] = {}
    for r in rows:
        sets.setdefault(r.set_key, []).append(r)

    cancel = cancel or threading.Event()
    for i, (key, set_rows) in enumerate(sets.items(), start=1):
        if cancel.is_set():
            break
        _undo_set(cfg, session, key, set_rows, record_run, index)
        session.commit()
        if progress:
            progress(i, len(sets))


def _undo_set(
    cfg: Config, session: Session, key: str, rows: list[MoveHistory], record_run: Run, index: LibraryIndex
) -> None:
    problem = _check(cfg, rows)
    if problem:
        log.warning("Cannot undo %s: %s", key, problem)
        _record(session, record_run, rows, "failed", problem)
        record_run.errors += 1
        return

    moved = []
    try:
        for r in rows:
            move_file(cfg.abs(r.new_path), cfg.abs(r.old_path))
            moved.append(r)
    except OSError as e:
        log.error("Undo of %s failed: %s", key, e)
        for r in reversed(moved):
            try:
                move_file(cfg.abs(r.old_path), cfg.abs(r.new_path))
            except OSError:
                log.critical("Could not roll back undo of %s", r.old_path, exc_info=True)
        _record(session, record_run, rows, "failed", str(e))
        record_run.errors += 1
        return

    for r in rows:
        r.status = "undone"
        index.remove(r.new_path)
        top_folder = cfg.abs(r.new_path.split("/", 1)[0])  # Organised, Duplicates or Rejected
        prune_empty_dirs(cfg.abs(r.new_path).parent, top_folder)
    _record(session, record_run, rows, "done")
    record_run.files_moved += 1


def _check(cfg: Config, rows: list[MoveHistory]) -> str | None:
    for r in rows:
        dest, origin = cfg.abs(r.new_path), cfg.abs(r.old_path)
        try:
            st = dest.stat()
        except FileNotFoundError:
            return f"{r.new_path} is no longer there"
        if (r.size is not None and st.st_size != r.size) or (
            r.mtime is not None and not same_mtime(st.st_mtime, r.mtime)
        ):
            return f"{r.new_path} has changed since it was moved"
        if origin.exists():
            return f"Something already exists at {r.old_path}"
    return None


def _record(session: Session, record_run: Run, rows: list[MoveHistory], status: str, error: str | None = None):
    now = datetime.now()
    for r in rows:
        session.add(
            MoveHistory(
                run_id=record_run.run_id,
                set_key=r.set_key,
                action="restore",
                is_main=r.is_main,
                old_path=r.new_path,
                new_path=r.old_path,
                hash=r.hash,
                size=r.size,
                mtime=r.mtime,
                photo_date=r.photo_date,
                date_source=r.date_source,
                status=status,
                error=error,
                action_time=now,
            )
        )

