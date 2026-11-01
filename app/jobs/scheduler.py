"""Scheduled jobs. Runs inside the single Gunicorn worker, so each job exists once."""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import Config
from app.database import Database
from app.jobs.runner import JobRunner, RunInProgress
from app.services import settings
from app.services.scanner import count_photos

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, cfg: Config, db: Database, runner: JobRunner):
        self.cfg = cfg
        self.db = db
        self.runner = runner
        self._sched = BackgroundScheduler()

    def start(self) -> None:
        self._sched.add_job(self._index, CronTrigger(day_of_week="sun", hour=3), id="index")
        self._sched.add_job(self._count_inbox, IntervalTrigger(minutes=15), id="inbox_count")
        self.apply_settings()
        self._sched.start()
        log.info("Scheduler started")

    def apply_settings(self) -> None:
        with self.db.session() as s:
            opts = settings.load(s)
        if self._sched.get_job("organise"):
            self._sched.remove_job("organise")
        if opts.schedule_enabled:
            hour, minute = opts.schedule_hour_minute
            self._sched.add_job(self._organise, CronTrigger(hour=hour, minute=minute), id="organise")
            log.info("Organise scheduled daily at %02d:%02d", hour, minute)
        else:
            log.info("Scheduled organise is off")

    def next_organise(self):
        job = self._sched.get_job("organise")
        return job.next_run_time if job else None

    def _organise(self) -> None:
        self._start("organise")

    def _index(self) -> None:
        self._start("index")

    def _start(self, kind: str) -> None:
        try:
            self.runner.start(kind, trigger="schedule")
        except RunInProgress:
            log.warning("Scheduled %s skipped: another run is in progress", kind)

    def _count_inbox(self) -> None:
        try:
            count = count_photos(self.cfg.inbox)
        except OSError:
            log.warning("Could not count Inbox", exc_info=True)
            return
        with self.db.session() as s:
            settings.set_values(s, {"stat_inbox_count": str(count)})
