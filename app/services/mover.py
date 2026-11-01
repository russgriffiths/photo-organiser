"""Applies a plan to the NAS. The only code that moves photos into the library."""

import errno
import logging
import os
import shutil
import threading
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Config
from app.models import Run
from app.services import history
from app.services.folders import prune_empty_dirs
from app.services.hashing import sha256_file
from app.services.index import LibraryIndex, same_mtime
from app.services.planner import PlannedSet

log = logging.getLogger(__name__)


def move_file(src: Path, dst: Path) -> None:
    """Move without ever overwriting. Rename when possible; otherwise copy, verify, delete."""
    if dst.exists():
        raise FileExistsError(f"Destination exists: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dst)
        return
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
    tmp = dst.with_name(dst.name + ".partial")
    shutil.copy2(src, tmp)
    if sha256_file(tmp) != sha256_file(src):
        tmp.unlink()
        raise OSError(f"Copy verification failed for {src}")
    os.replace(tmp, dst)
    src.unlink()


class Mover:
    def __init__(
        self,
        cfg: Config,
        session: Session,
        run: Run,
        index: LibraryIndex,
        cancel: threading.Event | None = None,
        progress: Callable[[int, int], None] | None = None,
    ):
        self.cfg = cfg
        self.session = session
        self.run = run
        self.index = index
        self.cancel = cancel or threading.Event()
        self.progress = progress

    def apply(self, plan: list[PlannedSet]) -> None:
        for i, ps in enumerate(plan, start=1):
            if self.cancel.is_set():
                log.info("Run %s cancelled after %d of %d sets", self.run.run_id, i - 1, len(plan))
                break
            self._apply_set(ps)
            self.session.commit()  # history is written per set, before the next one
            if self.progress:
                self.progress(i, len(plan))

    def _apply_set(self, ps: PlannedSet) -> None:
        if ps.action == "skip":
            history.record_set(self.session, self.cfg, self.run.run_id, ps, "done")
            return

        problem = self._check(ps)
        if problem:
            log.warning("Skipped %s: %s", ps.key, problem)
            history.record_set(self.session, self.cfg, self.run.run_id, ps, "failed", problem)
            self.run.errors += 1
            return

        moved = []
        try:
            for f in ps.files:
                move_file(f.source, f.dest)
                moved.append(f)
        except OSError as e:
            log.error("Failed to move %s: %s", ps.key, e)
            for f in reversed(moved):
                try:
                    move_file(f.dest, f.source)
                except OSError:
                    log.critical("Could not roll back %s -> %s", f.dest, f.source, exc_info=True)
            history.record_set(self.session, self.cfg, self.run.run_id, ps, "failed", str(e))
            self.run.errors += 1
            return

        history.record_set(self.session, self.cfg, self.run.run_id, ps, "done")
        history.count_into(self.run, ps)
        for f in ps.files:
            self.index.add(self.cfg.rel(f.dest), f.size, f.mtime, ps.hash if f.is_main else None)
        # A photo set always shares one folder; drop it (and emptied parents) from the Inbox.
        prune_empty_dirs(ps.main.source.parent, self.cfg.inbox)

    def _check(self, ps: PlannedSet) -> str | None:
        """Re-check the plan against the disk: the source may have changed since it was planned."""
        for f in ps.files:
            try:
                st = f.source.stat()
            except FileNotFoundError:
                return f"Source no longer exists: {self.cfg.rel(f.source)}"
            if st.st_size != f.size or not same_mtime(st.st_mtime, f.mtime):
                return f"Source changed since it was planned: {self.cfg.rel(f.source)}"
            if f.dest is None:
                return "No destination planned"
            if f.dest.exists():
                return f"Destination now exists: {self.cfg.rel(f.dest)}; run a new dry run"
        return None
