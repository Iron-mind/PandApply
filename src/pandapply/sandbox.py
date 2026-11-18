"""Synthetic ATS with its own durable receipt store; never contacts an external site."""

import hashlib
import html
import re
import secrets
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware


class SandboxRejected(ValueError):
    pass


class SandboxConflict(ValueError):
    pass


def store_submission(database: Path, *, idempotency_key: str, name: str, email: str, contents: bytes) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", idempotency_key):
        raise SandboxRejected("Invalid idempotency key")
    if not name.strip() or len(name) > 200 or not re.fullmatch(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.test", email, flags=re.IGNORECASE):
        raise SandboxRejected("Synthetic name and .test email required")
    if len(contents) > 2_000_000 or not contents.startswith(b"%PDF-"):
        raise SandboxRejected("A PDF of at most 2 MB is required")
    request_hash = hashlib.sha256(
        (name.strip() + "\0" + email.lower() + "\0" + hashlib.sha256(contents).hexdigest()).encode()
    ).hexdigest()
    with closing(sqlite3.connect(database, timeout=10)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT request_hash,receipt FROM submissions WHERE idempotency_key=?",
                              (idempotency_key,)).fetchone()
        if existing:
            if existing[0] != request_hash:
                raise SandboxConflict("Idempotency key already used for different data")
            return existing[1]
        receipt = "sandbox-" + str(uuid.uuid4())
        db.execute("INSERT INTO submissions VALUES (?,?,?)", (idempotency_key, request_hash, receipt))
    return receipt


def create_sandbox(database: Path, *, token: str | None = None) -> FastAPI:
    """Create a local-only fake ATS for synthetic identities and test PDFs."""
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS submissions ("
                   "idempotency_key TEXT PRIMARY KEY, request_hash TEXT NOT NULL, receipt TEXT NOT NULL)")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])

    @app.get("/", response_class=HTMLResponse)
    def form():
        token_field = (f"<input type='hidden' name='sandbox_token' value='{html.escape(token, quote=True)}'>"
                       if token else "")
        return ("<!doctype html><html lang='es'><meta charset='utf-8'><title>ATS de prueba</title>"
                "<h1>ATS de prueba: solo datos ficticios</h1><form action='/submit' method='post' "
                "enctype='multipart/form-data'>" + token_field + "<label>Clave <input name='idempotency_key' required></label>"
                "<label>Nombre ficticio <input name='name' required></label>"
                "<label>Correo .test <input type='email' name='email' required></label>"
                "<label>CV PDF <input type='file' name='cv' accept='.pdf' required></label>"
                "<button type='submit'>Enviar al simulador</button></form></html>")

    @app.post("/submit")
    async def submit(idempotency_key: Annotated[str, Form()], name: Annotated[str, Form()],
                     email: Annotated[str, Form()], cv: Annotated[UploadFile, File()],
                     sandbox_token: Annotated[str, Form()] = ""):
        if token and not secrets.compare_digest(sandbox_token.encode(), token.encode()):
            raise HTTPException(403, "Invalid sandbox token")
        contents = await cv.read(2_000_001)
        try:
            receipt = store_submission(database, idempotency_key=idempotency_key, name=name,
                                       email=email, contents=contents)
        except SandboxRejected as exc:
            raise HTTPException(400, str(exc)) from exc
        except SandboxConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"receipt": receipt, "sandbox": True}

    return app
