import os
import time
from pathlib import Path

import pytest

from app import create_app
from app.config import Config
from app.database import Database
from app.services.hashing import sha256_file

OLD = time.time() - 3600  # older than the "still being copied" window


class FakeReader:
    """Stands in for ExifTool. Tags are keyed by file name; UNREADABLE names return None."""

    def __init__(self, tags: dict[str, dict] | None = None, unreadable: set[str] | None = None):
        self.tags = tags or {}
        self.unreadable = unreadable or set()
        self.on_read = None  # optional hook, e.g. to press Cancel mid-read

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def read(self, paths, progress=None, cancel=None):
        if self.on_read:
            self.on_read()
        out = {}
        for p in paths:
            if cancel is not None and cancel.is_set():
                break
            out[p] = None if p.name in self.unreadable else dict(self.tags.get(p.name, {}))
            if progress:
                progress(len(out), len(paths))
        return out


def put(path: Path, content: bytes = b"photo", mtime: float = OLD) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    os.utime(path, (mtime, mtime))
    return path


def exif(date: str) -> dict:
    return {"DateTimeOriginal": date}


def snapshot(root: Path) -> dict[str, str]:
    """rel path -> hash of every file under root."""
    return {p.relative_to(root).as_posix(): sha256_file(p) for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def cfg(tmp_path) -> Config:
    photos = tmp_path / "photos"
    for name in ("Inbox", "Organised", "Duplicates", "Rejected"):
        (photos / name).mkdir(parents=True)
    return Config(photos_root=photos, data_dir=tmp_path / "data", start_scheduler=False, testing=True)


@pytest.fixture
def db(cfg) -> Database:
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    database = Database(cfg.db_path)
    database.create_all()
    return database


@pytest.fixture
def reader() -> FakeReader:
    return FakeReader()


@pytest.fixture
def app(cfg, reader):
    flask_app = create_app(cfg, reader_factory=lambda: reader)
    flask_app.config["WTF_CSRF_ENABLED"] = False
    return flask_app


@pytest.fixture
def runner(app):
    return app.extensions["organiser"].runner
