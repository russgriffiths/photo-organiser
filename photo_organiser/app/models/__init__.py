from datetime import datetime

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Run(Base):
    """One organise, undo, restore or index run. Counts are photo sets, not files."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String, unique=True)
    kind: Mapped[str]  # organise | undo | restore | index
    dry_run: Mapped[bool] = mapped_column(default=False)
    trigger: Mapped[str]  # schedule | manual
    status: Mapped[str]  # running | done | failed | cancelled
    undoes_run_id: Mapped[str | None]
    from_preview_run_id: Mapped[str | None]
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    files_scanned: Mapped[int] = mapped_column(default=0)
    files_moved: Mapped[int] = mapped_column(default=0)
    duplicates: Mapped[int] = mapped_column(default=0)
    rejected: Mapped[int] = mapped_column(default=0)
    errors: Mapped[int] = mapped_column(default=0)
    message: Mapped[str | None]

    @property
    def duration_seconds(self) -> int | None:
        if self.finished_at is None:
            return None
        return int((self.finished_at - self.started_at).total_seconds())


class MoveHistory(Base):
    """One row per file per run. Paths are relative to the photos root."""

    __tablename__ = "move_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), index=True)
    set_key: Mapped[str]  # groups a photo with its companion files
    action: Mapped[str]  # move | duplicate | reject | skip | restore
    is_main: Mapped[bool] = mapped_column(default=True)
    old_path: Mapped[str]
    new_path: Mapped[str | None]
    hash: Mapped[str | None] = mapped_column(index=True)
    size: Mapped[int | None]
    mtime: Mapped[float | None] = mapped_column(Float)
    photo_date: Mapped[datetime | None]
    date_source: Mapped[str | None]
    matched_path: Mapped[str | None]  # the file a duplicate matched
    status: Mapped[str]  # planned | done | failed | undone
    error: Mapped[str | None]
    action_time: Mapped[datetime]


class FileIndex(Base):
    """Cache of files in Organised, Duplicates and Rejected. Rebuildable from the NAS."""

    __tablename__ = "file_index"

    path: Mapped[str] = mapped_column(primary_key=True)
    size: Mapped[int] = mapped_column(index=True)
    mtime: Mapped[float] = mapped_column(Float)
    hash: Mapped[str | None] = mapped_column(index=True)
    indexed_at: Mapped[datetime]


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str]
