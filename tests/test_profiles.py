import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from pandapply.profiles import add_profile, edit_profile, import_cv, list_profiles
from pandapply.storage import connect, migrate
from pandapply.timezones import normalize_timezone


@pytest.mark.parametrize(("value", "hours"), [("UTC-5", -5), (" utc-05:00 ", -5),
                                             ("UTC+3", 3), ("UTC+14", 14), ("UTC-12", -12), ("UTC+0", 0)])
def test_offset_input_keeps_correct_sign_and_persists_as_iana(tmp_path, value, hours):
    path = tmp_path / "data.db"
    migrate(path)
    with connect(path) as db:
        add_profile(db, "Backend", value, {})
        zone = db.execute("SELECT timezone FROM master_profile").fetchone()[0]
        assert datetime(2026, 1, 1, tzinfo=ZoneInfo(zone)).utcoffset() == timedelta(hours=hours)
        assert datetime(2026, 7, 1, tzinfo=ZoneInfo(zone)).utcoffset() == timedelta(hours=hours)


def test_timezone_errors_are_actionable_and_cities_remain_unchanged():
    assert normalize_timezone("America/Bogota") == "America/Bogota"
    with pytest.raises(ValueError, match="America/Bogota"):
        normalize_timezone("UTC-99")
    with pytest.raises(ValueError, match="Asia/Kolkata"):
        normalize_timezone("UTC+5:30")


def test_profiles_persist_and_cv_original_is_unchanged(tmp_path):
    path = tmp_path / "pandapply.db"
    migrate(path)
    cv = tmp_path / "resume.pdf"
    content = b"%PDF-1.4 test"
    cv.write_bytes(content)
    with connect(path) as db:
        profile = add_profile(db, "Backend", "UTC", {"roles": ["Python"]})
        document = import_cv(db, profile, cv)
    with connect(path) as db:
        assert list_profiles(db)[0]["preferences"] == {"roles": ["Python"]}
        row = db.execute("SELECT sha256, file_path FROM documents WHERE id=?", (document,)).fetchone()
        assert row["sha256"] == hashlib.sha256(content).hexdigest()
        assert row["file_path"] == str(cv.resolve())
    assert cv.read_bytes() == content


def test_invalid_profile_and_missing_file_are_rejected(tmp_path):
    path = tmp_path / "pandapply.db"
    migrate(path)
    with connect(path) as db:
        with pytest.raises(ValueError):
            add_profile(db, "", "UTC", {})
        with pytest.raises(ValueError):
            add_profile(db, "Backend", "Invalid/Timezone", {})
        bad = tmp_path / "file.txt"
        bad.write_text("test")
        with pytest.raises(ValueError):
            import_cv(db, "missing", bad)


def test_profile_edit_preserves_preferences_and_detects_stale_version(tmp_path):
    path = tmp_path / "pandapply.db"
    migrate(path)
    with connect(path) as db:
        profile = add_profile(db, "Backend", "UTC", {"work_mode": "remote"})
        assert edit_profile(db, profile, name="Senior Backend", expected_version=1) == 2
        with pytest.raises(ValueError, match="another operation"):
            edit_profile(db, profile, preferences={}, expected_version=1)
        assert list_profiles(db)[0]["preferences"] == {"work_mode": "remote"}
        assert edit_profile(db, profile, name="Senior Backend", expected_version=2) == 2
