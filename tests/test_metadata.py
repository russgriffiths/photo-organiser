from datetime import datetime

from app.services.metadata import (
    DEFAULT_DATE_SOURCES,
    _clean,
    choose_date,
    date_from_filename,
    parse_exif_date,
)

NOW = datetime(2026, 10, 31, 12, 0)
MTIME = datetime(2026, 1, 15, 9, 0).timestamp()
WITH_MTIME = (*DEFAULT_DATE_SOURCES, "mtime")
ALL_TAGS = {"DateTimeDigitized": "2024:03:03 10:00:00", "CreateDate": "2023:02:02 10:00:00",
            "DateTimeOriginal": "2022:01:01 10:00:00"}


def test_default_order_prefers_date_taken():
    assert choose_date(ALL_TAGS, "x.jpg", MTIME, now=NOW) == (datetime(2022, 1, 1, 10), "DateTimeOriginal")


def test_custom_order_is_followed():
    sources = ("filename", "CreateDate", "DateTimeOriginal")
    assert choose_date(ALL_TAGS, "IMG_20250704_183012.jpg", MTIME, sources, NOW) == (
        datetime(2025, 7, 4, 18, 30, 12), "filename")
    assert choose_date(ALL_TAGS, "x.jpg", MTIME, sources, NOW) == (datetime(2023, 2, 2, 10), "CreateDate")


def test_unticked_sources_are_never_used():
    assert choose_date(ALL_TAGS, "IMG_20250704_183012.jpg", MTIME, ("DateTimeDigitized",), NOW) == (
        datetime(2024, 3, 3, 10), "DateTimeDigitized")
    assert choose_date({}, "IMG_20250704_183012.jpg", MTIME, ("DateTimeOriginal",), NOW) == (None, None)


def test_invalid_tag_falls_through_to_next():
    tags = {"DateTimeOriginal": "0000:00:00 00:00:00", "CreateDate": "2023:02:02 10:00:00"}
    assert choose_date(tags, "x.jpg", MTIME, now=NOW) == (datetime(2023, 2, 2, 10), "CreateDate")


def test_future_and_pre_1990_dates_are_rejected():
    tags = {"DateTimeOriginal": "2030:01:01 00:00:00", "CreateDate": "1980:01:01 00:00:00"}
    assert choose_date(tags, "x.jpg", MTIME, now=NOW) == (None, None)


def test_filename_date_used_when_no_tags():
    assert choose_date({}, "IMG_20250704_183012.jpg", MTIME, now=NOW) == (
        datetime(2025, 7, 4, 18, 30, 12), "filename")


def test_mtime_only_when_ticked():
    assert choose_date({}, "holiday.jpg", MTIME, now=NOW) == (None, None)
    assert choose_date({}, "holiday.jpg", MTIME, WITH_MTIME, NOW) == (datetime(2026, 1, 15, 9), "mtime")


def test_filename_patterns():
    assert date_from_filename("PXL_20241225_101500123.jpg") == datetime(2024, 12, 25)
    assert date_from_filename("20240101_120000.jpg") == datetime(2024, 1, 1, 12, 0, 0)
    assert date_from_filename("WhatsApp Image 2023-05-06 at 14.22.01.jpeg") == datetime(2023, 5, 6)
    assert date_from_filename("IMG_1234.JPG") is None
    assert date_from_filename("scan_20241399.jpg") is None


def test_exif_date_with_subseconds_and_timezone():
    assert parse_exif_date("2026:10:31 14:30:00.123+01:00") == datetime(2026, 10, 31, 14, 30)


def test_clean_strips_groups_and_flags_errors():
    assert _clean({"SourceFile": "a.jpg", "EXIF:DateTimeOriginal": "2026:10:31 10:00:00"}) == {
        "DateTimeOriginal": "2026:10:31 10:00:00"}
    assert _clean({"SourceFile": "a.jpg", "ExifTool:Error": "File format error"}) is None
