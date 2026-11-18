"""Explicit, one-attempt pilot invitation through the verified Hermes send CLI."""

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import uuid
from pathlib import Path

from pandapply.storage import now

INVITATION = "Hola, soy PandApply. ¿Quieres que ejecutemos la primera búsqueda de vacantes?"


def owner_jid(value: str) -> str:
    value = value.strip().removeprefix("+")
    if value.isdigit():
        value += "@s.whatsapp.net"
    if not re.fullmatch(r"[1-9][0-9]{7,14}@s\.whatsapp\.net", value):
        raise ValueError("Introduce tu número internacional, sin espacios, por ejemplo +573001234567")
    return value


class WhatsAppOutcomeUnknown(RuntimeError):
    pass


class HermesWhatsApp:
    def __init__(self, executable: Path, home: Path):
        self.executable = executable.expanduser().absolute()
        self.home = home.expanduser().resolve(strict=True)
        if not self.executable.is_file() or not self.home.is_dir():
            raise ValueError("Se necesita el ejecutable y el perfil existente de Hermes")
        if os.name == "nt" and self.executable.suffix.lower() in (".cmd", ".bat", ".ps1"):
            raise ValueError("Este lanzador Hermes necesita configuración manual; no se enviará el piloto")

    def send(self, target: str, message: str) -> str:
        try:
            result = subprocess.run([str(self.executable), "send", "--to", "whatsapp:" + owner_jid(target),
                                     "--json", "--file", "-"], input=message, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=45, check=False,
                                    env={**os.environ, "HERMES_HOME": str(self.home)})
            if result.returncode or len(result.stdout) > 100_000:
                raise ValueError("Hermes no confirmó el envío")
            receipt = json.loads(result.stdout)
            if (not isinstance(receipt, dict) or receipt.get("success") is not True or receipt.get("error")
                    or receipt.get("skipped") or receipt.get("partial_success")
                    or not isinstance(receipt.get("message_id"), str) or not receipt["message_id"]):
                raise ValueError("Hermes no devolvió un recibo inequívoco")
            return receipt["message_id"]
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            raise WhatsAppOutcomeUnknown("El envío es incierto. Revisa WhatsApp antes de volver a intentarlo") from exc


def invite(db: sqlite3.Connection, transport: HermesWhatsApp, target: str, *, confirm: bool) -> dict:
    """The wizard authorizes exactly this greeting to the explicitly chosen owner."""
    if not confirm:
        raise ValueError("Confirma el envío del saludo antes de ejecutarlo")
    target = owner_jid(target)
    db.execute("BEGIN IMMEDIATE")
    try:
        existing = db.execute("SELECT id,delivery_status FROM event_outbox WHERE event_type='PILOT_INVITATION' "
                              "ORDER BY created_at LIMIT 1").fetchone()
        if existing:
            status = existing["delivery_status"]
            if status == "SENDING":
                status = "UNKNOWN"
            db.commit()
            return {"id": existing["id"], "status": status, "resent": False}
        identifier = str(uuid.uuid4())
        owner_hash = hashlib.sha256(target.encode()).hexdigest()
        payload = json.dumps({"owner_hash": owner_hash, "text": INVITATION, "receipt": None}, ensure_ascii=False)
        db.execute("INSERT INTO event_outbox (id,event_type,payload_redacted_json,destination,delivery_status,"
                   "attempt_count,created_at) VALUES (?,'PILOT_INVITATION',?,'whatsapp','SENDING',1,?)",
                   (identifier, payload, now()))
        db.commit()
    except Exception:
        db.rollback()
        raise
    try:
        receipt = transport.send(target, INVITATION)
        with db:
            changed = db.execute("UPDATE event_outbox SET delivery_status='SENT',delivered_at=?,payload_redacted_json=? "
                       "WHERE id=? AND delivery_status='SENDING'", (now(), json.dumps({"owner_hash": owner_hash,
                        "text": INVITATION, "receipt": receipt}, ensure_ascii=False), identifier)).rowcount
            if changed != 1:
                raise WhatsAppOutcomeUnknown("El estado local cambió durante el envío")
        return {"id": identifier, "status": "SENT", "resent": False}
    except Exception as exc:
        with db:
            db.execute("UPDATE event_outbox SET delivery_status='UNKNOWN' WHERE id=? AND delivery_status='SENDING'",
                       (identifier,))
        raise WhatsAppOutcomeUnknown("Resultado del piloto incierto; no se reintentará automáticamente") from exc
