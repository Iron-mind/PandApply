import pytest
from pypdf import PdfReader

from pandapply.cv import render_cv
from pandapply.memory import decide_skill, propose_skill
from pandapply.profiles import add_profile
from pandapply.storage import connect, migrate


def test_cv_only_contains_approved_claims_and_never_overwrites(tmp_path):
    db_path = tmp_path / "db.sqlite"
    migrate(db_path)
    output = tmp_path / "profile.pdf"
    with connect(db_path) as db:
        profile = add_profile(db, "Backend", "UTC", {})
        approved = propose_skill(db, profile, "Python")
        propose_skill(db, profile, "UnapprovedSecretSkill")
        with pytest.raises(ValueError, match="verified"):
            render_cv(db, profile, output)
        decide_skill(db, approved, approve=True)
        document = render_cv(db, profile, output)
        text = "".join(page.extract_text() for page in PdfReader(output).pages)
        assert "Python" in text
        assert "UnapprovedSecretSkill" not in text
        row = db.execute("SELECT claim_ids_json FROM documents WHERE id=?", (document,)).fetchone()
        assert db.execute("SELECT id FROM knowledge_claims").fetchone()[0] in row[0]
        with pytest.raises(FileExistsError):
            render_cv(db, profile, output)
