"""file_index: what is already in Organised, Duplicates and Rejected.

Hashes are computed only when a duplicate check needs them, and kept until the
file's size or modified time changes.
"""

import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import Config
from app.models import FileIndex
from app.services.hashing import sha256_file
from app.services.scanner import COMPANION_EXTS, is_supported, walk_files

log = logging.getLogger(__name__)

MTIME_TOLERANCE = 0.01


def same_mtime(a: float, b: float) -> bool:
    return abs(a - b) < MTIME_TOLERANCE


class LibraryIndex:
    def __init__(self, session: Session, cfg: Config, hasher: Callable[[Path], str] = sha256_file):
        self.session = session
        self.cfg = cfg
        self.hasher = hasher
        self.organised_prefix = cfg.organised_dir + "/"

    def organised_paths_with_size(self, size: int) -> list[str]:
        return list(
            self.session.scalars(
                select(FileIndex.path).where(
                    FileIndex.size == size, FileIndex.path.startswith(self.organised_prefix)
                )
            )
        )

    def hash_of(self, rel: str) -> str | None:
        """Cached hash of an indexed file; drops the row if the file has gone."""
        path = self.cfg.abs(rel)
        row = self.session.get(FileIndex, rel)
        try:
            st = path.stat()
        except FileNotFoundError:
            if row is not None:
                self.session.delete(row)
            return None
        if row is not None and row.hash and row.size == st.st_size and same_mtime(row.mtime, st.st_mtime):
            return row.hash
        digest = self.hasher(path)
        self.add(rel, st.st_size, st.st_mtime, digest)
        return digest

    def add(self, rel: str, size: int, mtime: float, digest: str | None = None) -> None:
        row = self.session.get(FileIndex, rel)
        if row is None:
            self.session.add(
                FileIndex(path=rel, size=size, mtime=mtime, hash=digest, indexed_at=datetime.now())
            )
        else:
            if row.size != size or not same_mtime(row.mtime, mtime):
                row.hash = None
            row.size, row.mtime, row.indexed_at = size, mtime, datetime.now()
            if digest:
                row.hash = digest

    def remove(self, rel: str) -> None:
        row = self.session.get(FileIndex, rel)
        if row is not None:
            self.session.delete(row)


def rebuild(session: Session, cfg: Config, progress: Callable[[int], None] | None = None) -> int:
    """Walk the indexed folders and bring file_index in line with the disk.

    Lists files only; contents are not read, so this is a directory walk.
    Existing hashes are kept for files whose size and modified time are unchanged.
    """
    existing = {row.path: row for row in session.scalars(select(FileIndex))}
    seen: set[str] = set()
    count = 0
    now = datetime.now()
    for folder in cfg.indexed_folders:
        if not folder.is_dir():
            continue
        for path in walk_files(folder):
            if not is_supported(path):
                continue
            rel = cfg.rel(path)
            st = path.stat()
            seen.add(rel)
            row = existing.get(rel)
            if row is None:
                session.add(FileIndex(path=rel, size=st.st_size, mtime=st.st_mtime, hash=None, indexed_at=now))
            elif row.size != st.st_size or not same_mtime(row.mtime, st.st_mtime):
                row.size, row.mtime, row.hash, row.indexed_at = st.st_size, st.st_mtime, None, now
            count += 1
            if progress and count % 500 == 0:
                progress(count)
                session.flush()
    gone = [p for p in existing if p not in seen]
    for i in range(0, len(gone), 500):
        session.execute(delete(FileIndex).where(FileIndex.path.in_(gone[i : i + 500])))
    log.info("Index rebuilt: %d files, %d removed", count, len(gone))
    return count


def photo_count(session: Session, folder: str) -> int:
    """Photos (not companion files) indexed under a top-level folder."""
    q = select(func.count()).select_from(FileIndex).where(FileIndex.path.startswith(folder + "/"))
    for ext in COMPANION_EXTS:
        q = q.where(~FileIndex.path.ilike(f"%{ext}"))
    return session.scalar(q) or 0
