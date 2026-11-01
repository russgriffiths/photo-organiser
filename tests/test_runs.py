"""End-to-end runs through the job runner against a temporary folder."""

import os

import pytest
from sqlalchemy import select

from app.jobs.runner import RunInProgress
from app.models import MoveHistory, Run
from tests.conftest import exif, put, snapshot


@pytest.fixture
def library(cfg, reader):
    reader.tags.update({
        "IMG_1.HEIC": exif("2026:10:31 14:00:00"),
        "IMG_2.JPG": exif("2025:12:25 09:00:00"),
        "dup.jpg": exif("2025:12:25 09:00:00"),
    })
    put(cfg.inbox / "IMG_1.HEIC", b"heic")
    put(cfg.inbox / "IMG_1.MOV", b"live")
    put(cfg.inbox / "IMG_2.JPG", b"jpeg")
    put(cfg.inbox / "dup.jpg", b"already have it")
    put(cfg.inbox / "undated.png", b"png")
    put(cfg.organised / "2019/05/05/original.jpg", b"already have it")
    return cfg


def run_and_wait(runner, kind, **kw):
    run_id = runner.start(kind, wait=True, **kw)
    db = runner.db
    with db.session() as s:
        return s.scalar(select(Run).where(Run.run_id == run_id))


def test_organise_then_undo_restores_every_file(library, runner):
    before = snapshot(library.photos_root)
    run_and_wait(runner, "index")
    run = run_and_wait(runner, "organise")

    assert run.status == "done"
    assert (run.files_moved, run.duplicates, run.rejected, run.errors) == (2, 1, 1, 0)
    assert (library.organised / "2026/10/31/IMG_1.HEIC").exists()
    assert (library.organised / "2026/10/31/IMG_1.MOV").exists()
    assert (library.organised / "2025/12/25/IMG_2.JPG").exists()
    assert (library.duplicates / "2025/12/25/dup.jpg").exists()
    assert (library.rejected / "Undated/undated.png").exists()
    assert not any(library.inbox.iterdir())

    undo = run_and_wait(runner, "undo", target_run_id=run.run_id)
    assert undo.status == "done"
    assert undo.files_moved == 4
    assert snapshot(library.photos_root) == before
    # Empty date folders are cleaned up.
    assert not (library.organised / "2026").exists()


def test_dry_run_moves_nothing_and_organise_applies_the_preview(library, runner):
    before = snapshot(library.photos_root)
    dry = run_and_wait(runner, "organise", dry_run=True)
    assert dry.status == "done"
    assert snapshot(library.photos_root) == before

    real = run_and_wait(runner, "organise", from_preview=dry.run_id)
    assert real.status == "done"
    assert (library.organised / "2026/10/31/IMG_1.HEIC").exists()


def test_file_changed_after_dry_run_is_skipped(library, runner):
    dry = run_and_wait(runner, "organise", dry_run=True)
    changed = library.inbox / "IMG_2.JPG"
    changed.write_bytes(b"edited after preview")

    real = run_and_wait(runner, "organise", from_preview=dry.run_id)
    assert real.errors == 1
    assert changed.exists()
    with runner.db.session() as s:
        row = s.scalar(select(MoveHistory).where(MoveHistory.run_id == real.run_id, MoveHistory.status == "failed"))
    assert "changed since it was planned" in row.error


def test_undo_skips_a_file_that_was_changed_after_moving(library, runner):
    run = run_and_wait(runner, "organise")
    moved = library.organised / "2025/12/25/IMG_2.JPG"
    moved.write_bytes(b"edited in the library")
    os.utime(moved, (1, 1))

    undo = run_and_wait(runner, "undo", target_run_id=run.run_id)
    assert undo.errors == 1
    assert moved.exists()
    assert (library.inbox / "IMG_1.HEIC").exists()


def test_restore_one_duplicate_to_inbox(library, runner):
    run_and_wait(runner, "index")
    run = run_and_wait(runner, "organise")
    with runner.db.session() as s:
        row = s.scalar(select(MoveHistory).where(MoveHistory.run_id == run.run_id, MoveHistory.action == "duplicate"))
    run_and_wait(runner, "restore", target_run_id=run.run_id, set_key=row.set_key)
    assert (library.inbox / "dup.jpg").exists()
    assert (library.organised / "2026/10/31/IMG_1.HEIC").exists()


def test_emptied_inbox_subfolders_are_removed(cfg, reader, runner):
    reader.tags.update({"a.jpg": exif("2025:07:04 10:00:00"), "b.jpg": exif("2025:07:04 11:00:00")})
    put(cfg.inbox / "Holiday" / "Day 1" / "a.jpg", b"a")
    put(cfg.inbox / "Holiday" / "Day 1" / "@eaDir" / "a.jpg" / "SYNOPHOTO_THUMB_M.jpg", b"thumb")
    put(cfg.inbox / "Holiday" / "Day 1" / "Thumbs.db", b"x")
    put(cfg.inbox / "Notes" / "b.jpg", b"b")
    put(cfg.inbox / "Notes" / "readme.txt", b"keep me")
    (cfg.inbox / "Untouched").mkdir()

    run = run_and_wait(runner, "organise")
    assert run.files_moved == 2
    assert not (cfg.inbox / "Holiday").exists()  # emptied, parent removed too
    assert (cfg.inbox / "Notes" / "readme.txt").exists()  # other files keep the folder
    assert (cfg.inbox / "Untouched").is_dir()  # folders this run didn't touch are left
    assert cfg.inbox.is_dir()

    run_and_wait(runner, "undo", target_run_id=run.run_id)
    assert (cfg.inbox / "Holiday" / "Day 1" / "a.jpg").exists()  # undo recreates the subfolder
    assert not (cfg.organised / "2025").exists()


def test_cancel_while_reading_metadata_records_nothing(library, reader, runner):
    before = snapshot(library.photos_root)
    reader.on_read = runner.cancel  # user presses Cancel during "reading metadata"
    run = run_and_wait(runner, "organise", dry_run=True)
    assert run.status == "cancelled"
    with runner.db.session() as s:
        assert s.scalar(select(MoveHistory).where(MoveHistory.run_id == run.run_id)) is None
    assert snapshot(library.photos_root) == before


def test_metadata_and_planning_report_progress(library, runner, monkeypatch):
    seen = []
    original = runner._step
    monkeypatch.setattr(runner, "_step", lambda d, t: (seen.append((runner.progress["stage"], d, t)), original(d, t)))
    run_and_wait(runner, "organise", dry_run=True)
    assert ("reading metadata", 4, 4) in seen
    assert ("planning", 4, 4) in seen


def test_only_one_run_at_a_time(library, runner):
    assert runner._lock.acquire(blocking=False)
    try:
        with pytest.raises(RunInProgress):
            runner.start("organise")
    finally:
        runner._lock.release()


def test_interrupted_run_is_marked_failed_on_restart(library, runner):
    from datetime import datetime

    with runner.db.session() as s:
        s.add(Run(run_id="stale", kind="organise", trigger="manual", status="running", started_at=datetime.now()))
    runner.recover()
    with runner.db.session() as s:
        assert s.scalar(select(Run.status).where(Run.run_id == "stale")) == "failed"
