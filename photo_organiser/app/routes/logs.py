from collections import deque

from flask import Blueprint, abort, render_template, request, send_file

from app import state

bp = Blueprint("logs", __name__)

SEVERITY = ["INFO", "WARNING", "ERROR", "CRITICAL"]
CHOICES = ["ALL", "INFO", "WARNING", "ERROR"]
TAIL = 500


@bp.route("/logs")
def index():
    level = request.args.get("level", "ALL")
    wanted = SEVERITY[SEVERITY.index(level):] if level in SEVERITY else None
    log_file = state().cfg.log_dir / "app.log"
    lines: list[str] = []
    if log_file.exists():
        with open(log_file, encoding="utf-8", errors="replace") as f:
            matching = f if wanted is None else (l for l in f if any(f" {w} " in l for w in wanted))
            lines = list(deque(matching, maxlen=TAIL))
    return render_template("logs.html", lines=list(reversed(lines)), level=level, levels=CHOICES)


@bp.route("/logs/download")
def download():
    log_file = state().cfg.log_dir / "app.log"
    if not log_file.exists():
        abort(404)
    return send_file(log_file, as_attachment=True, download_name="photo-organiser.log")
