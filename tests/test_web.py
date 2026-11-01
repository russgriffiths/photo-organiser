from tests.conftest import exif, put


def login(client, password="correct horse"):
    client.post("/setup", data={"password": password, "confirm": password})


def test_first_visit_asks_for_a_password(app):
    client = app.test_client()
    assert client.get("/").headers["Location"].endswith("/setup")
    login(client)
    assert client.get("/").status_code == 200


def test_pages_need_login(app):
    login(app.test_client())
    client = app.test_client()  # new client, no session
    for path in ("/", "/preview", "/duplicates", "/history", "/settings", "/logs"):
        assert "/login" in client.get(path).headers["Location"]
    assert client.get("/health").status_code == 200


def test_wrong_password_rejected(app):
    login(app.test_client())
    client = app.test_client()
    r = client.post("/login", data={"password": "nope"})
    assert b"Wrong password" in r.data


def test_every_page_renders_after_a_run(app, cfg, reader):
    reader.tags["IMG_1.JPG"] = exif("2026:10:31 14:00:00")
    put(cfg.inbox / "IMG_1.JPG")
    client = app.test_client()
    login(client)
    client.post("/run/dry-run")
    app.extensions["organiser"].runner.wait(10)
    for path in ("/", "/preview", "/preview?filter=move", "/duplicates", "/history", "/settings", "/logs"):
        r = client.get(path)
        assert r.status_code == 200, path
    assert b"Organised/2026/10/31/IMG_1.JPG" in client.get("/preview").data


VALID = {"schedule_time": "03:30", "duplicate_handling": "skip", "stable_minutes": "10",
         "folder_layout": "day", "date_sources": ["DateTimeOriginal", "filename"]}


def test_settings_validation(app):
    client = app.test_client()
    login(client)
    r = client.post("/settings", data={**VALID, "schedule_time": "25:00"}, follow_redirects=True)
    assert b"HH:MM" in r.data
    r = client.post("/settings", data={**VALID, "date_sources": []}, follow_redirects=True)
    assert b"Tick at least one" in r.data
    r = client.post("/settings", data={**VALID, "folder_layout": "week"}, follow_redirects=True)
    assert b"folder structure" in r.data
    r = client.post("/settings", data=VALID, follow_redirects=True)
    assert b"Settings saved" in r.data


def test_folder_layout_and_date_order_are_saved(app):
    from app.services import settings

    client = app.test_client()
    login(client)
    client.post("/settings", data={**VALID, "folder_layout": "month", "date_sources": ["filename", "mtime", "CreateDate"]})
    with app.extensions["organiser"].db.session() as s:
        saved = settings.load(s)
    assert saved.folder_layout == "month"
    assert saved.date_sources == ["filename", "mtime", "CreateDate"]
    # The page lists ticked sources first, in the saved order.
    html = client.get("/settings").get_data(as_text=True)
    assert html.index('value="filename"') < html.index('value="mtime"') < html.index('value="CreateDate"')
    assert html.index('value="CreateDate"') < html.index('value="DateTimeOriginal"')


def test_schedule_starts_switched_off(db):
    from app.services import settings

    with db.session() as s:
        assert settings.load(s).schedule_enabled is False


def test_old_modified_date_setting_carries_over(db):
    from app.services import settings

    with db.session() as s:
        settings.set_values(s, {"allow_mtime_fallback": "1"})
    with db.session() as s:
        assert settings.load(s).date_sources[-1] == "mtime"


def test_csrf_is_enforced(cfg, reader):
    from app import create_app

    app = create_app(cfg, reader_factory=lambda: reader)
    client = app.test_client()
    assert client.post("/setup", data={"password": "x" * 10, "confirm": "x" * 10}).status_code == 400
