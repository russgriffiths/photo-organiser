"""Runs jobs in a background thread, one at a time."""

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import select

from app.config import Config
from app.database import Database
from app.models import MoveHistory, Run
from app.services import history, index as index_service, settings, undo
from app.services.index import LibraryIndex
from app.services.metadata import MetadataReader
from app.services.mover import Mover
from app.services.planner import PlanOptions, Planner
from app.services.scanner import count_photos, scan

log = logging.getLogger(__name__)

PREVIEW_MAX_AGE = timedelta(hours=24)


class RunInProgress(Exception):
    pass


class JobRunner:
    def __init__(self, cfg: Config, db: Database, reader_factory: Callable[[], MetadataReader]):
        self.cfg = cfg
        self.db = db
        self.reader_factory = reader_factory
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self.progress: dict = {}

    # --- lifecycle -------------------------------------------------------

    def recover(self) -> None:
        """Mark runs left 'running' by a crash or restart as failed. Their moves stay undoable."""
        with self.db.session() as s:
            for run in s.scalars(select(Run).where(Run.status == "running")):
                run.status = "failed"
                run.finished_at = run.finished_at or datetime.now()
                run.message = "Interrupted: the app stopped during this run"
                log.warning("Marked interrupted run %s as failed", run.run_id)

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def cancel(self) -> None:
        if self.busy:
            self._cancel.set()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # --- starting runs ---------------------------------------------------

    def start(
        self,
        kind: str,
        trigger: str = "manual",
        dry_run: bool = False,
        target_run_id: str | None = None,
        set_key: str | None = None,
        from_preview: str | None = None,
        wait: bool = False,
    ) -> str:
        """Start a run in the background and return its run_id. Raises RunInProgress if one is running."""
        if not self._lock.acquire(blocking=False):
            raise RunInProgress("A run is already in progress")
        try:
            with self.db.session() as s:
                if s.scalar(select(Run).where(Run.status == "running")):
                    raise RunInProgress("A run is already in progress")
                run = Run(
                    run_id=self._new_run_id(s),
                    kind=kind,
                    dry_run=dry_run,
                    trigger=trigger,
                    status="running",
                    undoes_run_id=target_run_id,
                    from_preview_run_id=from_preview,
                    started_at=datetime.now(),
                )
                s.add(run)
                run_id = run.run_id
        except Exception:
            self._lock.release()
            raise

        self._cancel.clear()
        self.progress = {"run_id": run_id, "kind": kind, "dry_run": dry_run, "stage": "starting", "done": 0, "total": 0}
        args = (run_id, kind, dry_run, target_run_id, set_key, from_preview)
        self._thread = threading.Thread(target=self._execute, args=args, name=f"run-{run_id}", daemon=True)
        self._thread.start()
        log.info("Started %s run %s (%s%s)", kind, run_id, trigger, ", dry run" if dry_run else "")
        if wait:
            self._thread.join()
        return run_id

    def _new_run_id(self, s) -> str:
        base = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_id, n = base, 1
        while s.scalar(select(Run).where(Run.run_id == run_id)):
            n += 1
            run_id = f"{base}-{n}"
        return run_id

    # --- execution -------------------------------------------------------

    def _execute(self, run_id, kind, dry_run, target_run_id, set_key, from_preview) -> None:
        try:
            with self.db.session() as s:
                run = s.scalar(select(Run).where(Run.run_id == run_id))
                try:
                    if kind == "organise":
                        self._organise(s, run, dry_run, from_preview)
                    elif kind in ("undo", "restore"):
                        self._stage("restoring")
                        undo.undo(
                            self.cfg, s, target_run_id, run, LibraryIndex(s, self.cfg),
                            set_key=set_key, cancel=self._cancel, progress=self._step,
                        )
                    elif kind == "index":
                        self._stage("indexing")
                        run.files_scanned = index_service.rebuild(s, self.cfg, progress=self._count)
                    else:
                        raise ValueError(f"Unknown run kind: {kind}")
                    run.status = "cancelled" if self._cancel.is_set() else "done"
                except Exception as e:
                    s.rollback()
                    log.exception("Run %s failed", run_id)
                    run = s.scalar(select(Run).where(Run.run_id == run_id))
                    run.status = "failed"
                    run.message = str(e)[:500]
                run.finished_at = datetime.now()
                log.info(
                    "Run %s %s: moved %d, duplicates %d, rejected %d, errors %d",
                    run_id, run.status, run.files_moved, run.duplicates, run.rejected, run.errors,
                )
        finally:
            self.progress = {}
            self._lock.release()

    def _organise(self, s, run: Run, dry_run: bool, from_preview: str | None) -> None:
        opts = settings.load(s)
        index = LibraryIndex(s, self.cfg)
        if from_preview:
            self._stage("loading preview")
            plan = history.plan_from_dry_run(s, self.cfg, from_preview)
            run.files_scanned = len(plan)
        else:
            self._stage("scanning")
            sets, unstable = scan(self.cfg.inbox, opts.stable_minutes * 60)
            run.files_scanned = len(sets)
            settings.set_values(s, {"stat_inbox_count": str(count_photos(self.cfg.inbox))})
            s.commit()  # keep the count even if a later stage fails
            if unstable:
                log.info("%d photo sets still changing; left for the next run", unstable)
            self._stage("reading metadata")
            with self.reader_factory() as reader:
                tags = reader.read([ps.main.path for ps in sets], progress=self._step, cancel=self._cancel)
            if self._cancel.is_set():
                return  # nothing recorded or moved; files not yet read would look unreadable
            self._stage("planning")
            planner = Planner(
                self.cfg, index, PlanOptions(opts.duplicate_handling, opts.date_sources, opts.folder_layout)
            )
            plan = planner.plan(sets, tags, progress=self._step, cancel=self._cancel)
            if self._cancel.is_set():
                return  # a partial plan is never recorded or applied

        if dry_run:
            for ps in plan:
                history.record_set(s, self.cfg, run.run_id, ps, "planned")
                history.count_into(run, ps)
        else:
            self._stage("moving")
            Mover(self.cfg, s, run, index, self._cancel, self._step).apply(plan)
        settings.set_values(s, {"stat_inbox_count": str(count_photos(self.cfg.inbox))})

    def _stage(self, name: str) -> None:
        self.progress = {**self.progress, "stage": name, "done": 0, "total": 0}

    def _step(self, done: int, total: int) -> None:
        self.progress = {**self.progress, "done": done, "total": total}

    def _count(self, done: int) -> None:
        self.progress = {**self.progress, "done": done}


def usable_preview(s, now: datetime | None = None) -> Run | None:
    """The latest dry run, if under 24 hours old and nothing has been organised since."""
    now = now or datetime.now()
    latest_dry = s.scalar(
        select(Run)
        .where(Run.kind == "organise", Run.dry_run.is_(True), Run.status == "done")
        .order_by(Run.started_at.desc())
    )
    if latest_dry is None or now - latest_dry.started_at > PREVIEW_MAX_AGE:
        return None
    later = s.scalar(
        select(Run).where(
            Run.kind.in_(("organise", "undo", "restore")),
            Run.dry_run.is_(False),
            Run.started_at > latest_dry.started_at,
        )
    )
    return None if later else latest_dry


def undoable_run(s, run_id: str | None = None) -> Run | None:
    """A real organise run with moves still in place (the latest one if run_id is None)."""
    q = select(Run).where(Run.kind == "organise", Run.dry_run.is_(False))
    if run_id:
        q = q.where(Run.run_id == run_id)
    for run in s.scalars(q.order_by(Run.started_at.desc())):
        has_moves = s.scalar(
            select(MoveHistory.id).where(
                MoveHistory.run_id == run.run_id,
                MoveHistory.status == "done",
                MoveHistory.action.in_(undo.REVERSIBLE),
            ).limit(1)
        )
        if has_moves:
            return run
        if run_id:
            return None
    return None
