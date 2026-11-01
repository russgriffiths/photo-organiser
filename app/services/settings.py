"""User-editable settings, stored as key/value rows in the settings table."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Setting
from app.services.metadata import DATE_SOURCES, DEFAULT_DATE_SOURCES

FOLDER_LAYOUTS = {"year": "YYYY", "month": "YYYY/MM", "day": "YYYY/MM/DD"}

DEFAULTS = {
    "schedule_enabled": "1",
    "schedule_time": "02:00",
    "duplicate_handling": "move",  # move | skip
    "folder_layout": "day",  # a key of FOLDER_LAYOUTS
    "date_sources": ",".join(DEFAULT_DATE_SOURCES),  # in priority order
    "stable_minutes": "5",
}


@dataclass
class AppSettings:
    schedule_enabled: bool
    schedule_time: str
    duplicate_handling: str
    folder_layout: str
    date_sources: list[str]
    stable_minutes: int

    @property
    def schedule_hour_minute(self) -> tuple[int, int]:
        hour, minute = self.schedule_time.split(":")
        return int(hour), int(minute)


def get_value(session: Session, key: str) -> str | None:
    row = session.get(Setting, key)
    if row is not None:
        return row.value
    return DEFAULTS.get(key)


def set_values(session: Session, values: dict[str, str]) -> None:
    for key, value in values.items():
        row = session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=value))
        else:
            row.value = value


def parse_date_sources(value: str) -> list[str]:
    """Known sources in the stored order, each once."""
    sources: list[str] = []
    for s in value.split(","):
        s = s.strip()
        if s in DATE_SOURCES and s not in sources:
            sources.append(s)
    return sources


def load(session: Session) -> AppSettings:
    stored = {s.key: s.value for s in session.scalars(select(Setting))}
    values = {**DEFAULTS, **stored}
    # Before date_sources existed, the modified-date fallback was a separate yes/no setting.
    if "date_sources" not in stored and stored.get("allow_mtime_fallback") == "1":
        values["date_sources"] += ",mtime"
    return AppSettings(
        schedule_enabled=values["schedule_enabled"] == "1",
        schedule_time=values["schedule_time"],
        duplicate_handling=values["duplicate_handling"],
        folder_layout=values["folder_layout"] if values["folder_layout"] in FOLDER_LAYOUTS else "day",
        date_sources=parse_date_sources(values["date_sources"]) or list(DEFAULT_DATE_SOURCES),
        stable_minutes=int(values["stable_minutes"]),
    )
