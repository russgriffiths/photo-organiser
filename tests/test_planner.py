from datetime import datetime

from app.services import index as index_service
from app.services.index import LibraryIndex
from app.services.planner import PlanOptions, Planner
from app.services.scanner import scan
from tests.conftest import FakeReader, exif, put

NOW = datetime(2026, 10, 31, 12, 0)


def plan(cfg, db, reader, options=PlanOptions()):
    with db.session() as s:
        index_service.rebuild(s, cfg)
        sets, _ = scan(cfg.inbox, 300)
        tags = reader.read([x.main.path for x in sets])
        return Planner(cfg, LibraryIndex(s, cfg), options, NOW).plan(sets, tags)


def rel(cfg, ps):
    return [cfg.rel(f.dest) if f.dest else None for f in ps.files]


def test_moves_into_date_folder_with_companions(cfg, db):
    put(cfg.inbox / "IMG_1.HEIC")
    put(cfg.inbox / "IMG_1.MOV")
    [ps] = plan(cfg, db, FakeReader({"IMG_1.HEIC": exif("2026:10:31 14:00:00")}))
    assert ps.action == "move"
    assert rel(cfg, ps) == ["Organised/2026/10/31/IMG_1.HEIC", "Organised/2026/10/31/IMG_1.MOV"]


def test_name_collision_with_different_content_gets_suffix(cfg, db):
    put(cfg.organised / "2026/10/31/IMG_1.JPG", b"other camera")
    put(cfg.inbox / "IMG_1.JPG", b"mine")
    [ps] = plan(cfg, db, FakeReader({"IMG_1.JPG": exif("2026:10:31 14:00:00")}))
    assert ps.action == "move"
    assert rel(cfg, ps) == ["Organised/2026/10/31/IMG_1_1.JPG"]


def test_two_inbox_files_same_name_same_day(cfg, db):
    put(cfg.inbox / "a" / "IMG_1.JPG", b"one")
    put(cfg.inbox / "b" / "IMG_1.JPG", b"two")
    reader = FakeReader({"IMG_1.JPG": exif("2026:10:31 14:00:00")})
    a, b = plan(cfg, db, reader)
    assert rel(cfg, a) == ["Organised/2026/10/31/IMG_1.JPG"]
    assert rel(cfg, b) == ["Organised/2026/10/31/IMG_1_1.JPG"]


def test_duplicate_of_library_file_found_even_under_another_date(cfg, db):
    put(cfg.organised / "2020/01/01/old.jpg", b"same bytes")
    put(cfg.inbox / "copy.jpg", b"same bytes")
    [ps] = plan(cfg, db, FakeReader({"copy.jpg": exif("2026:10:31 14:00:00")}))
    assert ps.action == "duplicate"
    assert ps.matched == "Organised/2020/01/01/old.jpg"
    assert rel(cfg, ps) == ["Duplicates/2026/10/31/copy.jpg"]


def test_duplicate_within_the_same_batch(cfg, db):
    put(cfg.inbox / "a.jpg", b"same")
    put(cfg.inbox / "b.jpg", b"same")
    reader = FakeReader({"a.jpg": exif("2026:10:31 14:00:00"), "b.jpg": exif("2026:10:31 14:00:00")})
    a, b = plan(cfg, db, reader)
    assert a.action == "move"
    assert b.action == "duplicate"
    assert b.matched == "Organised/2026/10/31/a.jpg"


def test_same_size_different_content_is_not_duplicate(cfg, db):
    put(cfg.organised / "2020/01/01/x.jpg", b"aaaa")
    put(cfg.inbox / "y.jpg", b"bbbb")
    [ps] = plan(cfg, db, FakeReader({"y.jpg": exif("2026:10:31 14:00:00")}))
    assert ps.action == "move"


def test_skip_mode_leaves_duplicates_in_inbox(cfg, db):
    put(cfg.organised / "2020/01/01/old.jpg", b"same")
    put(cfg.inbox / "copy.jpg", b"same")
    [ps] = plan(cfg, db, FakeReader({"copy.jpg": exif("2026:10:31 14:00:00")}), PlanOptions(duplicate_handling="skip"))
    assert ps.action == "skip"
    assert rel(cfg, ps) == [None]


def test_year_and_month_folder_layouts(cfg, db):
    put(cfg.inbox / "a.jpg", b"a")
    reader = FakeReader({"a.jpg": exif("2025:07:04 10:00:00")})
    [by_year] = plan(cfg, db, reader, PlanOptions(folder_layout="year"))
    assert rel(cfg, by_year) == ["Organised/2025/a.jpg"]
    [by_month] = plan(cfg, db, reader, PlanOptions(folder_layout="month"))
    assert rel(cfg, by_month) == ["Organised/2025/07/a.jpg"]


def test_duplicates_follow_the_folder_layout(cfg, db):
    put(cfg.organised / "2020/old.jpg", b"same")
    put(cfg.inbox / "copy.jpg", b"same")
    [ps] = plan(cfg, db, FakeReader({"copy.jpg": exif("2025:07:04 10:00:00")}), PlanOptions(folder_layout="year"))
    assert (ps.action, rel(cfg, ps)) == ("duplicate", ["Duplicates/2025/copy.jpg"])


def test_date_source_order_is_used(cfg, db):
    put(cfg.inbox / "IMG_20200101_120000.jpg")
    reader = FakeReader({"IMG_20200101_120000.jpg": exif("2025:07:04 10:00:00")})
    [ps] = plan(cfg, db, reader, PlanOptions(date_sources=("filename", "DateTimeOriginal")))
    assert (ps.date_source, rel(cfg, ps)) == ("filename", ["Organised/2020/01/01/IMG_20200101_120000.jpg"])


def test_undated_and_unreadable_are_rejected(cfg, db):
    put(cfg.inbox / "nodate.jpg")
    put(cfg.inbox / "broken.jpg", b"broken")
    reader = FakeReader(unreadable={"broken.jpg"})
    broken, nodate = plan(cfg, db, reader)
    assert (nodate.action, rel(cfg, nodate)) == ("reject", ["Rejected/Undated/nodate.jpg"])
    assert (broken.action, rel(cfg, broken)) == ("reject", ["Rejected/Unreadable/broken.jpg"])
