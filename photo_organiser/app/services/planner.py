"""Works out what should happen to each photo set. Touches no files."""

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.config import Config
from app.services.index import LibraryIndex
from app.services.metadata import DEFAULT_DATE_SOURCES, Progress, Tags, choose_date
from app.services.scanner import FileInfo, PhotoSet


@dataclass
class PlannedFile:
    source: Path
    dest: Path | None
    size: int
    mtime: float
    is_main: bool


@dataclass
class PlannedSet:
    key: str
    action: str  # move | duplicate | reject | skip
    files: list[PlannedFile]
    photo_date: datetime | None = None
    date_source: str | None = None
    hash: str | None = None
    matched: str | None = None
    reason: str | None = None

    @property
    def main(self) -> PlannedFile:
        return self.files[0]


@dataclass
class PlanOptions:
    duplicate_handling: str = "move"  # move | skip
    date_sources: Sequence[str] = DEFAULT_DATE_SOURCES
    folder_layout: str = "day"  # year | month | day


def date_folder(date: datetime, layout: str) -> Path:
    """YYYY, YYYY/MM or YYYY/MM/DD."""
    if layout == "year":
        return Path(f"{date:%Y}")
    if layout == "month":
        return Path(f"{date:%Y}", f"{date:%m}")
    return Path(f"{date:%Y}", f"{date:%m}", f"{date:%d}")


@dataclass
class _BatchEntry:
    """A photo already planned for Organised in this run, for duplicate checks within the batch."""

    source: Path
    dest_rel: str
    digest: str | None = None


class Planner:
    def __init__(self, cfg: Config, index: LibraryIndex, options: PlanOptions, now: datetime | None = None):
        self.cfg = cfg
        self.index = index
        self.options = options
        self.now = now
        self._reserved: set[Path] = set()
        self._batch: dict[int, list[_BatchEntry]] = {}

    def plan(
        self,
        sets: list[PhotoSet],
        metadata: dict[Path, Tags | None],
        progress: Progress | None = None,
        cancel: threading.Event | None = None,
    ) -> list[PlannedSet]:
        """Plan every set. Returns a partial plan if `cancel` is set; callers must not apply it."""
        self._reserved = set()
        self._batch = {}
        planned = []
        for i, s in enumerate(sets, start=1):
            if cancel is not None and cancel.is_set():
                break
            planned.append(self._plan_one(s, metadata.get(s.main.path)))
            if progress and (i % 50 == 0 or i == len(sets)):
                progress(i, len(sets))
        return planned

    def _plan_one(self, s: PhotoSet, tags: Tags | None) -> PlannedSet:
        if tags is None:
            return self._to_folder(
                s, "reject", self.cfg.rejected / "Unreadable", reason="Unreadable or unsupported file"
            )
        date, source = choose_date(tags, s.main.path.name, s.main.mtime, self.options.date_sources, self.now)
        if date is None:
            return self._to_folder(s, "reject", self.cfg.rejected / "Undated", reason="No usable date found")

        day = date_folder(date, self.options.folder_layout)
        matched, digest = self._find_duplicate(s.main, self.cfg.organised / day / s.main.path.name)
        if matched:
            if self.options.duplicate_handling == "skip":
                return PlannedSet(
                    s.key, "skip", self._files(s, None), date, source, digest, matched,
                    reason=f"Duplicate of {matched}; left in Inbox",
                )
            return self._to_folder(s, "duplicate", self.cfg.duplicates / day, date, source, digest, matched)

        planned = self._to_folder(s, "move", self.cfg.organised / day, date, source, digest)
        self._batch.setdefault(s.main.size, []).append(
            _BatchEntry(s.main.path, self.cfg.rel(planned.main.dest), digest)
        )
        return planned

    def _find_duplicate(self, main: FileInfo, natural_dest: Path) -> tuple[str | None, str | None]:
        """Return (path of an identical file, this file's hash). Hashes only when sizes match."""
        candidates = self.index.organised_paths_with_size(main.size)
        natural_rel = self.cfg.rel(natural_dest)
        # The index may be stale, so also check the exact destination on disk.
        if natural_rel not in candidates and natural_dest.is_file() and natural_dest.stat().st_size == main.size:
            candidates.append(natural_rel)
        in_batch = self._batch.get(main.size, [])
        if not candidates and not in_batch:
            return None, None

        digest = self.index.hasher(main.path)
        for rel in candidates:
            if self.index.hash_of(rel) == digest:
                return rel, digest
        for entry in in_batch:
            if entry.digest is None:
                entry.digest = self.index.hasher(entry.source)
            if entry.digest == digest:
                return entry.dest_rel, digest
        return None, digest

    def _to_folder(
        self,
        s: PhotoSet,
        action: str,
        folder: Path,
        date: datetime | None = None,
        source: str | None = None,
        digest: str | None = None,
        matched: str | None = None,
        reason: str | None = None,
    ) -> PlannedSet:
        dests = self._free_names(s, folder)
        self._reserved.update(dests)
        return PlannedSet(s.key, action, self._files(s, dests), date, source, digest, matched, reason)

    def _free_names(self, s: PhotoSet, folder: Path) -> list[Path]:
        """Destinations for every file in the set, adding _1, _2... until none is taken.

        Companions take the main file's stem so the set stays paired after a rename.
        """
        stem = s.main.path.stem
        n = 0
        while True:
            name = stem if n == 0 else f"{stem}_{n}"
            dests = [folder / f"{name}{f.path.suffix}" for f in s.files]
            if not any(d in self._reserved or d.exists() for d in dests):
                return dests
            n += 1

    @staticmethod
    def _files(s: PhotoSet, dests: list[Path] | None) -> list[PlannedFile]:
        return [
            PlannedFile(f.path, dests[i] if dests else None, f.size, f.mtime, i == 0)
            for i, f in enumerate(s.files)
        ]
