"""Deployment configuration, read from environment variables, or from the
add-on options when running as a Home Assistant add-on.

User-editable settings (schedule, duplicate handling, ...) live in the database
instead; see app.services.settings.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    photos_root: Path
    data_dir: Path
    inbox_dir: str = "Inbox"
    organised_dir: str = "Organised"
    duplicates_dir: str = "Duplicates"
    rejected_dir: str = "Rejected"
    secret_key: str | None = None
    start_scheduler: bool = True
    testing: bool = False
    # Home Assistant add-on: served through ingress, and Home Assistant does the login.
    ha_addon: bool = False

    @property
    def password_required(self) -> bool:
        return not self.ha_addon

    @classmethod
    def from_env(cls) -> "Config":
        data_dir = Path(os.environ.get("DATA_DIR", "/data"))
        # The Supervisor writes the add-on's options here; it only exists inside Home Assistant.
        options_file = data_dir / "options.json"
        options = json.loads(options_file.read_text()) if options_file.exists() else None
        photos_root = (options or {}).get("photos_path") or os.environ.get("PHOTOS_ROOT", "/photos")
        return cls(
            photos_root=Path(photos_root),
            data_dir=data_dir,
            inbox_dir=os.environ.get("INBOX_DIR", "Inbox"),
            organised_dir=os.environ.get("ORGANISED_DIR", "Organised"),
            duplicates_dir=os.environ.get("DUPLICATES_DIR", "Duplicates"),
            rejected_dir=os.environ.get("REJECTED_DIR", "Rejected"),
            secret_key=os.environ.get("SECRET_KEY"),
            ha_addon=options is not None,
        )

    @property
    def inbox(self) -> Path:
        return self.photos_root / self.inbox_dir

    @property
    def organised(self) -> Path:
        return self.photos_root / self.organised_dir

    @property
    def duplicates(self) -> Path:
        return self.photos_root / self.duplicates_dir

    @property
    def rejected(self) -> Path:
        return self.photos_root / self.rejected_dir

    @property
    def indexed_folders(self) -> list[Path]:
        """Folders tracked in file_index (everything except Inbox)."""
        return [self.organised, self.duplicates, self.rejected]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "database.db"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    def rel(self, path: Path) -> str:
        """Path relative to the photos root, POSIX style, as stored in the database."""
        return path.relative_to(self.photos_root).as_posix()

    def abs(self, rel: str) -> Path:
        return self.photos_root / rel

    def check_folders(self) -> None:
        """Refuse to start if the NAS share isn't mounted (folders missing)."""
        missing = [p for p in (self.inbox, self.organised) if not p.is_dir()]
        if missing:
            raise RuntimeError(
                "Photo folders not found: "
                + ", ".join(str(p) for p in missing)
                + ". Is the NAS share mounted?"
            )
        for folder in (self.duplicates, self.rejected):
            folder.mkdir(exist_ok=True)
