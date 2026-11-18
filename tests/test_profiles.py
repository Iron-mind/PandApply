import hashlib

import pytest

from pandapply.profiles import add_profile, edit_profile, import_cv, list_profiles
from pandapply.storage import connect, migrate


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
