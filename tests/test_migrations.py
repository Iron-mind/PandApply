import sqlite3
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files

from pandapply.storage import connect, migrate


def test_upgrade_from_version_one_preserves_existing_profiles(tmp_path):
    path = tmp_path / "existing.db"
    sql = files("pandapply").joinpath("migrations/001_initial.sql").read_text("utf-8")
    with sqlite3.connect(path) as db:
        db.executescript(sql + "\nPRAGMA user_version=1;")
        db.execute("INSERT INTO master_profile VALUES ('owner','Owner','UTC','now')")
        db.execute("INSERT INTO professional_profiles VALUES ('p','owner','Backend','{}',1,1,'now','now')")
    migrate(path)
    with connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 10
        assert db.execute("SELECT name FROM professional_profiles WHERE id='p'").fetchone()[0] == "Backend"
        assert db.execute("SELECT count(*) FROM reply_attempts").fetchone()[0] == 0
    backups = list(tmp_path.glob("existing.db.backup-v1-*.sqlite"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 1
        assert backup.execute("SELECT name FROM professional_profiles WHERE id='p'").fetchone()[0] == "Backend"


def test_concurrent_initialization_is_serialized(tmp_path):
    path = tmp_path / "concurrent.db"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(migrate, (path, path)))
    assert results == [None, None]
    with connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 10
