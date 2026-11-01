"""Removing folders left empty once their photos have been moved out."""

import logging
import shutil
from pathlib import Path

from app.services.scanner import IGNORED_DIRS, IGNORED_NAMES

log = logging.getLogger(__name__)


def _is_clutter(entry: Path) -> bool:
    """Synology thumbnails (@eaDir) and OS files that don't make a folder worth keeping."""
    if entry.is_dir():
        return entry.name in IGNORED_DIRS
    return entry.name.lower() in IGNORED_NAMES


def prune_empty_dirs(folder: Path, stop_at: Path) -> None:
    """Remove `folder` and then its parents while they hold only clutter.

    Never removes `stop_at` itself or anything outside it. A folder with any
    other file or subfolder in it is kept.
    """
    while folder != stop_at and folder.is_relative_to(stop_at) and folder.is_dir():
        try:
            entries = list(folder.iterdir())
            if not all(_is_clutter(e) for e in entries):
                return
            for e in entries:
                shutil.rmtree(e) if e.is_dir() else e.unlink()
            folder.rmdir()
        except OSError:
            log.warning("Could not remove empty folder %s", folder, exc_info=True)
            return
        folder = folder.parent
