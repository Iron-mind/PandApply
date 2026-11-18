import pytest

from pandapply.memory import decide_skill, propose_skill
from pandapply.profiles import add_profile
from pandapply.storage import connect, migrate


def test_memory_requires_specific_affirmative_decision(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    with connect(path) as db:
        profile = add_profile(db, "Backend", "UTC", {})
        approved = propose_skill(db, profile, "Python")
        rejected = propose_skill(db, profile, "Java")
        assert db.execute("SELECT count(*) FROM knowledge_claims").fetchone()[0] == 0
        assert decide_skill(db, rejected, approve=False) == "REJECTED"
        assert db.execute("SELECT count(*) FROM knowledge_claims").fetchone()[0] == 0
        assert decide_skill(db, approved, approve=True) == "APPROVED"
        with pytest.raises(ValueError, match="already"):
            decide_skill(db, approved, approve=True)
        claim = db.execute("SELECT claim_json, approval_id FROM knowledge_claims").fetchone()
        assert "Python" in claim["claim_json"]
        assert claim["approval_id"] == approved
