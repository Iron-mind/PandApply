import pytest
from docx import Document
from pypdf import PdfWriter

from pandapply.documents import extract_cv
from pandapply.profiles import add_profile, import_cv
from pandapply.storage import connect, migrate


def test_extract_cv_is_unverified_and_detects_changes(tmp_path):
    database = tmp_path / "db.sqlite"
    migrate(database)
    path = tmp_path / "cv.docx"
    doc = Document()
    doc.add_paragraph("Python developer")
    doc.save(path)
    with connect(database) as db:
        profile_id = add_profile(db, "Developer", "UTC", {})
        document_id = import_cv(db, profile_id, path)
        result = extract_cv(db, document_id)
        assert "Python developer" in result["sections"][0]["text"]
        assert result["verification_status"] == "unverified"
        assert db.execute("SELECT count(*) FROM knowledge_claims").fetchone()[0] == 0
        path.write_bytes(b"modified")
        with pytest.raises(ValueError, match="changed"):
            extract_cv(db, document_id)


def test_extract_pdf_with_blank_page(tmp_path):
    database = tmp_path / "db.sqlite"
    migrate(database)
    path = tmp_path / "cv.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(path)
    with connect(database) as db:
        profile_id = add_profile(db, "Developer", "UTC", {})
        document_id = import_cv(db, profile_id, path)
        result = extract_cv(db, document_id)
        assert result["sections"] == [{"page": 1, "text": ""}]
