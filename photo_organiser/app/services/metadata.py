"""Reads capture dates. ExifTool does the reading; the date rules are plain functions."""

import logging
import re
import threading
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

Progress = Callable[[int, int], None]

# Tags read from every photo. ModifyDate is deliberately absent: editors overwrite it.
DATE_TAGS = ("DateTimeOriginal", "CreateDate", "DateTimeDigitized")

# Every way of finding a date, with the label shown on the Settings page.
# Which ones are used, and in what order, is a setting.
DATE_SOURCES = {
    "DateTimeOriginal": "Date taken (EXIF DateTimeOriginal)",
    "CreateDate": "Date created (EXIF CreateDate)",
    "DateTimeDigitized": "Date digitised (XMP DateTimeDigitized)",
    "filename": "Date in the file name (e.g. IMG_20250704_183012)",
    "mtime": "File modified date (low confidence: copying resets it)",
}
DEFAULT_DATE_SOURCES = ("DateTimeOriginal", "CreateDate", "DateTimeDigitized", "filename")
MIN_DATE = datetime(1990, 1, 1)

# IMG_20261031_143000, PXL_20261031_..., 20261031_143000, 2026-10-31 14.30.00, ...
FILENAME_DATE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])"
    r"(?:[-_ T.]{0,3}([01]\d|2[0-3])[-_.]?([0-5]\d)[-_.]?([0-5]\d))?(?!\d)"
)

Tags = dict[str, str]


class MetadataReader(Protocol):
    """Returns tags per path, or None for a file that could not be read.

    Stops early if `cancel` is set, so the result may then be missing paths.
    """

    def read(
        self,
        paths: list[Path],
        progress: Progress | None = None,
        cancel: threading.Event | None = None,
    ) -> dict[Path, Tags | None]: ...

    def __enter__(self) -> "MetadataReader": ...

    def __exit__(self, *exc) -> None: ...


class ExifToolReader:
    """One long-running ExifTool process, called in batches."""

    def __init__(self, batch_size: int = 100):
        self.batch_size = batch_size
        self._et = None

    def __enter__(self) -> "ExifToolReader":
        import exiftool  # imported here so tests and dev machines don't need ExifTool

        # -fast2: stop reading once the metadata is found, instead of scanning to the
        # end of each file for trailers and maker notes. Much less read over the network.
        self._et = exiftool.ExifToolHelper(common_args=["-G", "-n", "-fast2"], check_execute=False)
        self._et.run()
        return self

    def __exit__(self, *exc) -> None:
        if self._et is not None:
            self._et.terminate()
            self._et = None

    def read(
        self,
        paths: list[Path],
        progress: Progress | None = None,
        cancel: threading.Event | None = None,
    ) -> dict[Path, Tags | None]:
        out: dict[Path, Tags | None] = {}
        for i in range(0, len(paths), self.batch_size):
            if cancel is not None and cancel.is_set():
                break
            batch = paths[i : i + self.batch_size]
            try:
                results = self._et.get_tags([str(p) for p in batch], tags=list(DATE_TAGS))
            except Exception:
                log.warning("ExifTool batch failed; retrying files one by one", exc_info=True)
                results = [self._read_one(p) for p in batch]
            if len(results) != len(batch):
                log.warning("ExifTool returned %d results for %d files", len(results), len(batch))
                results = [self._read_one(p) for p in batch]
            for path, raw in zip(batch, results):
                out[path] = _clean(raw)
            if progress:
                progress(len(out), len(paths))
        return out

    def _read_one(self, path: Path) -> dict | None:
        try:
            results = self._et.get_tags([str(path)], tags=list(DATE_TAGS))
            return results[0] if results else None
        except Exception:
            log.warning("ExifTool could not read %s", path, exc_info=True)
            return None


def _clean(raw: dict | None) -> Tags | None:
    """Strip group prefixes ('EXIF:CreateDate' -> 'CreateDate'); None if ExifTool reported an error."""
    if raw is None:
        return None
    tags: Tags = {}
    for key, value in raw.items():
        name = key.split(":")[-1]
        if name == "Error":
            return None
        if name in DATE_TAGS and name not in tags:
            tags[name] = str(value)
    return tags


def _valid(d: datetime, now: datetime) -> bool:
    return MIN_DATE <= d <= now + timedelta(days=1)


def parse_exif_date(value: str | None) -> datetime | None:
    """'2026:10:31 14:30:00', optionally with sub-seconds or a timezone suffix."""
    if not value:
        return None
    value = value.strip()
    for fmt, length in (("%Y:%m:%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M:%S", 19), ("%Y:%m:%d", 10)):
        try:
            return datetime.strptime(value[:length], fmt)
        except ValueError:
            continue
    return None


def date_from_filename(name: str) -> datetime | None:
    for m in FILENAME_DATE.finditer(name):
        y, mo, d, h, mi, s = m.groups()
        try:
            return datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(s or 0))
        except ValueError:
            continue
    return None


def choose_date(
    tags: Tags,
    filename: str,
    mtime: float,
    sources: Sequence[str] = DEFAULT_DATE_SOURCES,
    now: datetime | None = None,
) -> tuple[datetime | None, str | None]:
    """Try each source in order; return (photo date, the source it came from), or (None, None)."""
    now = now or datetime.now()
    for source in sources:
        if source in DATE_TAGS:
            d = parse_exif_date(tags.get(source))
        elif source == "filename":
            d = date_from_filename(filename)
        elif source == "mtime":
            d = datetime.fromtimestamp(mtime)
        else:
            continue
        if d and _valid(d, now):
            return d, source
    return None, None
