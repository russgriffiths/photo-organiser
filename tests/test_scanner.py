import time

from app.services.scanner import scan
from tests.conftest import put


def _names(s):
    return sorted(f.path.name for f in s.files)


def test_live_photo_and_edits_travel_together(cfg):
    for name in ("IMG_0001.HEIC", "IMG_0001.MOV", "IMG_0001.AAE"):
        put(cfg.inbox / name)
    sets, _ = scan(cfg.inbox, 300)
    assert len(sets) == 1
    assert sets[0].main.path.name == "IMG_0001.HEIC"
    assert _names(sets[0]) == ["IMG_0001.AAE", "IMG_0001.HEIC", "IMG_0001.MOV"]


def test_raw_plus_jpeg_pair(cfg):
    put(cfg.inbox / "DSC_1.NEF")
    put(cfg.inbox / "DSC_1.JPG")
    put(cfg.inbox / "DSC_1.xmp")
    sets, _ = scan(cfg.inbox, 300)
    assert len(sets) == 1
    assert sets[0].main.path.name == "DSC_1.NEF"
    assert _names(sets[0]) == ["DSC_1.JPG", "DSC_1.NEF", "DSC_1.xmp"]


def test_same_stem_different_photos_are_separate(cfg):
    put(cfg.inbox / "a.jpg")
    put(cfg.inbox / "a.png")
    sets, _ = scan(cfg.inbox, 300)
    assert sorted(s.main.path.name for s in sets) == ["a.jpg", "a.png"]


def test_files_still_being_copied_are_left(cfg):
    put(cfg.inbox / "new.jpg", mtime=time.time())
    put(cfg.inbox / "old.jpg")
    sets, unstable = scan(cfg.inbox, 300)
    assert [s.main.path.name for s in sets] == ["old.jpg"]
    assert unstable == 1


def test_system_folders_hidden_files_and_lone_companions_ignored(cfg):
    put(cfg.inbox / "@eaDir" / "x.jpg")
    put(cfg.inbox / ".hidden.jpg")
    put(cfg.inbox / "clip.MOV")
    put(cfg.inbox / "notes.txt")
    put(cfg.inbox / "sub" / "deep.jpg")
    sets, _ = scan(cfg.inbox, 300)
    assert [s.main.path.name for s in sets] == ["deep.jpg"]
