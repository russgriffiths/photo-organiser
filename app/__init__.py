import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta
from logging.handlers import RotatingFileHandler

from flask import Flask, current_app
from flask_wtf.csrf import CSRFProtect

from app.config import Config
from app.database import Database
from app.ingress import IngressMiddleware
from app.jobs.runner import JobRunner
from app.jobs.scheduler import Scheduler
from app.services.metadata import ExifToolReader

csrf = CSRFProtect()


@dataclass
class AppState:
    cfg: Config
    db: Database
    runner: JobRunner
    scheduler: Scheduler | None


def state() -> AppState:
    return current_app.extensions["organiser"]


def _configure_logging(cfg: Config) -> None:
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(cfg.log_dir / "app.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
        # Also to stderr, for `docker logs` and the add-on's Log tab in Home Assistant.
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)
    # Request lines (the dashboard polls every 2 s) and scheduler ticks would bury the run logs.
    for noisy in ("werkzeug", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _secret_key(cfg: Config) -> str:
    """SECRET_KEY from the environment, or one generated once and kept in /data."""
    if cfg.secret_key:
        return cfg.secret_key
    path = cfg.data_dir / "secret_key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
    return path.read_text().strip()


def create_app(cfg: Config | None = None, reader_factory=None) -> Flask:
    cfg = cfg or Config.from_env()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    _configure_logging(cfg)
    if not cfg.testing:
        cfg.check_folders()

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=_secret_key(cfg),
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        # Own name: under ingress, other add-ons share the Home Assistant origin.
        SESSION_COOKIE_NAME="photo_organiser_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        TESTING=cfg.testing,
    )
    if cfg.ha_addon:
        app.wsgi_app = IngressMiddleware(app.wsgi_app)

    db = Database(cfg.db_path)
    db.create_all()
    runner = JobRunner(cfg, db, reader_factory or ExifToolReader)
    runner.recover()
    scheduler = Scheduler(cfg, db, runner) if cfg.start_scheduler else None
    app.extensions["organiser"] = AppState(cfg, db, runner, scheduler)

    csrf.init_app(app)

    from app.routes import auth, dashboard, duplicates, history, logs, preview, settings

    for module in (auth, dashboard, preview, duplicates, history, settings, logs):
        app.register_blueprint(module.bp)

    @app.template_filter("dt")
    def _format_dt(value):
        return value.strftime("%d-%b-%Y %H:%M") if value else "—"

    @app.context_processor
    def _auth_context():
        return {"password_required": cfg.password_required}

    if scheduler:
        scheduler.start()
    logging.getLogger(__name__).info("Photo Organiser started; photos at %s", cfg.photos_root)
    return app
