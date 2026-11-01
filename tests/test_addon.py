"""Running as a Home Assistant add-on: options.json, ingress prefix, no app password."""

import json

import pytest

from app import create_app
from app.config import Config
from app.ingress import SUPERVISOR_PROXY

PREFIX = "/api/hassio_ingress/abc123"
VIA_PROXY = {"REMOTE_ADDR": SUPERVISOR_PROXY}


@pytest.fixture
def addon_app(cfg, reader):
    cfg.ha_addon = True
    flask_app = create_app(cfg, reader_factory=lambda: reader)
    flask_app.config["WTF_CSRF_ENABLED"] = False
    return flask_app


def test_options_file_switches_to_addon_mode(tmp_path, monkeypatch):
    (tmp_path / "options.json").write_text(json.dumps({"photos_path": "/media/Photos"}))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PHOTOS_ROOT", "/ignored")
    cfg = Config.from_env()
    assert cfg.ha_addon and not cfg.password_required
    assert cfg.photos_root.as_posix() == "/media/Photos"


def test_standalone_without_options_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PHOTOS_ROOT", "/photos")
    cfg = Config.from_env()
    assert not cfg.ha_addon and cfg.password_required


def test_no_app_password_and_links_carry_the_ingress_prefix(addon_app):
    client = addon_app.test_client()
    r = client.get("/", headers={"X-Ingress-Path": PREFIX}, environ_base=VIA_PROXY)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert f'href="{PREFIX}/preview"' in html
    assert f'src="{PREFIX}/static/app.js' in html
    assert "Log out" not in html


def test_redirects_stay_under_the_prefix(addon_app):
    client = addon_app.test_client()
    r = client.post("/run/dry-run", headers={"X-Ingress-Path": PREFIX}, environ_base=VIA_PROXY)
    assert r.headers["Location"].endswith(f"{PREFIX}/")
    addon_app.extensions["organiser"].runner.wait(10)


def test_requests_not_from_the_supervisor_are_refused(addon_app):
    client = addon_app.test_client()
    assert client.get("/", environ_base={"REMOTE_ADDR": "192.168.1.50"}).status_code == 403
    # The container's own health check still works.
    assert client.get("/health", environ_base={"REMOTE_ADDR": "127.0.0.1"}).status_code == 200


def test_settings_page_hides_password_change(addon_app):
    html = addon_app.test_client().get("/settings", environ_base=VIA_PROXY).get_data(as_text=True)
    assert "Change password" not in html
    assert "Configuration tab" in html
