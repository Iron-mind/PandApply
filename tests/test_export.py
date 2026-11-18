import csv
import io
import json

from pandapply.export import export_data
from pandapply.profiles import add_profile
from pandapply.storage import connect, migrate


def test_export_local_data_without_gmail(tmp_path):
    path = tmp_path / "db.sqlite"
    migrate(path)
    with connect(path) as db:
        add_profile(db, "Backend", "UTC", {})
        data = json.loads(export_data(db, "json"))
        assert data["tables"]["professional_profiles"][0]["name"] == "Backend"
        assert data["tables"]["mailbox_messages"] == []
        rows = list(csv.DictReader(io.StringIO(export_data(db, "csv"))))
        profile = next(row for row in rows if row["table"] == "professional_profiles")
        assert json.loads(profile["row_json"])["name"] == "Backend"
