"""Generate a minimal PDF using only separately verified skills."""

import hashlib
import io
import json
import sqlite3
import uuid
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from pandapply.storage import now


def render_cv(db: sqlite3.Connection, profile_id: str, output: Path) -> str:
    profile = db.execute("SELECT name FROM professional_profiles WHERE id=? AND active=1", (profile_id,)).fetchone()
    if not profile:
        raise ValueError("Active profile not found")
    rows = db.execute("SELECT id,claim_json FROM knowledge_claims WHERE profile_id=? AND claim_type='skill' "
                      "AND verification_status IN ('master_confirmed','document_supported') ORDER BY created_at,id",
                      (profile_id,)).fetchall()
    skills = []
    for row in rows:
        payload = json.loads(row["claim_json"])
        if isinstance(payload, dict) and isinstance(payload.get("value"), str) and payload["value"].strip():
            skills.append((row["id"], payload["value"].strip()))
    if not skills:
        raise ValueError("At least one verified skill is required")
    output = output.expanduser().absolute()
    if output.suffix.lower() != ".pdf":
        raise ValueError("Generated CV must use a .pdf extension")
    styles = getSampleStyleSheet()
    buffer = io.BytesIO()
    story = [Paragraph(escape(profile["name"]), styles["Title"]), Spacer(1, 16),
             Paragraph("Habilidades verificadas", styles["Heading2"])]
    story.extend(Paragraph(escape(skill), styles["BodyText"]) for _, skill in skills)
    SimpleDocTemplate(buffer, title="Professional profile").build(story)
    content = buffer.getvalue()
    document_id = str(uuid.uuid4())
    created = False
    try:
        with output.open("xb") as target:
            created = True
            target.write(content)
        with db:
            db.execute("INSERT INTO documents (id,profile_id,kind,file_path,sha256,mime_type,"
                       "claim_ids_json,created_at) VALUES (?,?,'cv_generated',?,?,'application/pdf',?,?)",
                       (document_id, profile_id, str(output), hashlib.sha256(content).hexdigest(),
                        json.dumps([claim_id for claim_id, _ in skills]), now()))
    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise
    return document_id
