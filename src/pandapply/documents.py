"""Read imported CVs without treating extracted text as verified knowledge."""

import hashlib
import sqlite3
from pathlib import Path
from zipfile import BadZipFile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from pypdf import PdfReader
from pypdf.errors import PdfReadError


def extract_cv(db: sqlite3.Connection, document_id: str) -> dict:
    row = db.execute("SELECT file_path,sha256 FROM documents WHERE id=? AND kind='cv_original'",
                     (document_id,)).fetchone()
    if not row:
        raise ValueError("Original CV not found")
    path = Path(row["file_path"])
    if not path.is_file():
        raise ValueError("Original CV is not available")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != row["sha256"]:
        raise ValueError("Original CV has changed since import; import it again")
    try:
        if path.suffix.lower() == ".pdf":
            reader = PdfReader(path)
            if reader.is_encrypted:
                raise ValueError("Encrypted PDF requires manual handling")
            sections = [{"page": index, "text": page.extract_text() or ""}
                        for index, page in enumerate(reader.pages, 1)]
        elif path.suffix.lower() == ".docx":
            document = Document(path)
            text = "\n".join(paragraph.text for paragraph in document.paragraphs)
            sections = [{"page": None, "text": text}]
        else:
            raise ValueError("Unsupported CV format")
    except (PdfReadError, PackageNotFoundError, BadZipFile) as exc:
        raise ValueError("CV file is invalid or damaged") from exc
    return {"document_id": document_id, "source_sha256": row["sha256"],
            "verification_status": "unverified", "sections": sections}
