"""Walks the Inbox and groups files into photo sets (a photo plus its companions)."""

import os
import time
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

RAW_EXTS = {".cr2", ".nef", ".arw", ".dng"}
HEIC_EXTS = {".heic", ".heif"}
JPEG_EXTS = {".jpg", ".jpeg"}
MAIN_EXTS = RAW_EXTS | HEIC_EXTS | JPEG_EXTS | {".png"}
# Live Photo video, iOS edit file, XMP sidecar. Never organised on their own.
COMPANION_EXTS = {".mov", ".aae", ".xmp"}

IGNORED_DIRS = {"@eaDir", "#recycle", "#snapshot"}
IGNORED_NAMES = {"thumbs.db", ".ds_store", "desktop.ini"}


@dataclass
class FileInfo:
    path: Path
    size: int
    mtime: float

    @property
    def ext(self) -> str:
        return self.path.suffix.lower()


@dataclass
class PhotoSet:
    key: str
    main: FileInfo
    companions: list[FileInfo] = field(default_factory=list)

    @property
    def files(self) -> list[FileInfo]:
        return [self.main, *self.companions]


def _main_priority(f: FileInfo) -> int:
    if f.ext in RAW_EXTS:
        return 0
    if f.ext in HEIC_EXTS:
        return 1
    if f.ext in JPEG_EXTS:
        return 2
    return 3


def walk_files(root: Path) -> Iterator[Path]:
    """Every file under root, skipping NAS system folders and hidden files."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")]
        for name in filenames:
            if name.startswith(".") or name.lower() in IGNORED_NAMES:
                continue
            yield Path(dirpath) / name


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in MAIN_EXTS | COMPANION_EXTS


def count_photos(root: Path) -> int:
    return sum(1 for p in walk_files(root) if p.suffix.lower() in MAIN_EXTS)


def scan(inbox: Path, stable_seconds: int, now: float | None = None) -> tuple[list[PhotoSet], int]:
    """Return (photo sets ready to organise, number of sets skipped as still changing).

    A set is only picked up when none of its files changed in the last
    `stable_seconds`, so files still being copied in are left for the next run.
    """
    now = time.time() if now is None else now
    groups: dict[tuple[Path, str], list[FileInfo]] = defaultdict(list)
    for path in walk_files(inbox):
        if not is_supported(path):
            continue
        st = path.stat()
        groups[(path.parent, path.stem.lower())].append(FileInfo(path, st.st_size, st.st_mtime))

    sets: list[PhotoSet] = []
    unstable = 0
    for (parent, stem), files in groups.items():
        mains = sorted((f for f in files if f.ext in MAIN_EXTS), key=_main_priority)
        if not mains:
            continue  # companions with no photo stay in the Inbox
        main = mains[0]
        companions = [f for f in files if f.ext in COMPANION_EXTS]
        # A JPEG next to a RAW is the camera's preview copy and travels with it.
        if main.ext in RAW_EXTS:
            companions += [f for f in mains[1:] if f.ext in JPEG_EXTS]
        grouped = {id(main), *(id(c) for c in companions)}
        # Any other photo sharing the stem (e.g. IMG_1.jpg and IMG_1.png) is its own set.
        extras = [f for f in mains if id(f) not in grouped]

        rel_dir = parent.relative_to(inbox).as_posix()
        candidates = [PhotoSet(f"{rel_dir}/{stem}", main, companions)]
        candidates += [PhotoSet(f"{rel_dir}/{stem}{f.ext}", f) for f in extras]
        for s in candidates:
            if any(now - f.mtime < stable_seconds for f in s.files):
                unstable += 1
            else:
                sets.append(s)

    sets.sort(key=lambda s: str(s.main.path))
    return sets, unstable
