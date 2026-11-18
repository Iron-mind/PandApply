"""Offline discovery and conservative, explainable matching.

This module does not fetch pages or submit applications. Imported content is data,
not an instruction source, and missing constraints always require human review.
"""

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from pandapply.domain import Job, canonical_url
from pandapply.storage import now, save_job


class Candidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=500)
    company: str = Field(min_length=1, max_length=500)
    url: HttpUrl
    ats_requisition_id: str | None = None
    ats_provider: str | None = None
    skills: list[str] | None = None
    work_mode: str | None = None
    salary_usd_month: float | None = Field(default=None, ge=0)
    form: dict | None = None


class ProfileCriteria(BaseModel):
    model_config = ConfigDict(extra="ignore")

    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    confirmed_claims: list[str] = Field(default_factory=list)
    salary_min_usd_month: float | None = Field(default=None, ge=0)
    work_mode: str | None = None
    excluded_companies: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class Match:
    status: str
    score: float | None
    reasons: tuple[str, ...]


class DiscoveryPort(Protocol):
    provider_name: str
    def search(self) -> list[Candidate]: ...


class JsonDiscovery:
    """Read a locally selected JSON fixture; never access the network."""

    provider_name = "fixture"

    def __init__(self, path: Path):
        self.path = path

    def search(self) -> list[Candidate]:
        if self.path.stat().st_size > 5_000_000:
            raise ValueError("Fixture exceeds 5 MB")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ValueError("Fixture must contain a jobs array")  # noqa: TRY004
        if len(data["jobs"]) > 1000:
            raise ValueError("Fixture contains more than 1000 jobs")
        candidates = [Candidate.model_validate(item) for item in data["jobs"]]
        if self.provider_name == "fixture" and any(not str(candidate.url.host).lower().endswith(".test")
                                                    for candidate in candidates):
            raise ValueError("Synthetic fixtures may contain only .test hosts")
        if self.provider_name == "manual" and any(candidate.ats_provider and
                                                   candidate.ats_provider.casefold() == "fixture"
                                                   for candidate in candidates):
            raise ValueError("The fixture provider name is reserved for simulated jobs")
        return candidates


class ManualDiscovery(JsonDiscovery):
    """Import user-supplied job data. The provider never fetches remote sites."""

    provider_name = "manual"


def evaluate(criteria: ProfileCriteria, job: Candidate, *, min_score: float = 0.8) -> Match:
    reasons = []
    missing = []
    if job.company.casefold() in {company.casefold() for company in criteria.excluded_companies}:
        reasons.append("Empresa excluida por el perfil")
    if criteria.salary_min_usd_month is not None:
        if job.salary_usd_month is None:
            missing.append("Salario no especificado")
        elif job.salary_usd_month < criteria.salary_min_usd_month:
            reasons.append("Salario inferior al mínimo")
    if criteria.work_mode:
        if not job.work_mode:
            missing.append("Modalidad no especificada")
        elif job.work_mode.casefold() != criteria.work_mode.casefold():
            reasons.append("Modalidad incompatible")
    if reasons:
        return Match("SKIPPED_INELIGIBLE", 0.0, tuple(reasons))
    if job.form and job.form.get("captcha"):
        return Match("MANUAL_REVIEW", None, ("El formulario requiere CAPTCHA",))
    required = {s.casefold() for s in criteria.must_have_skills}
    confirmed = {s.casefold() for s in criteria.confirmed_claims}
    if required - confirmed:
        missing.append("Faltan evidencias confirmadas para habilidades obligatorias")
    if required and job.skills is None:
        missing.append("La vacante no especifica habilidades")
    elif required - {s.casefold() for s in job.skills or []}:
        missing.append("No se encontraron todas las habilidades obligatorias en la vacante")
    if missing:
        return Match("MANUAL_REVIEW", None, tuple(missing))
    optional = {s.casefold() for s in criteria.nice_to_have_skills} - required
    if not required and not optional:
        return Match("MANUAL_REVIEW", None, ("El perfil no define habilidades para evaluar",))
    if optional and job.skills is None:
        return Match("MANUAL_REVIEW", None, ("La vacante no especifica habilidades",))
    job_skills = {s.casefold() for s in job.skills or []}
    supported = optional & confirmed & job_skills
    denominator = len(required) + len(optional)
    score = (len(required) + len(supported)) / denominator
    explanation = f"Habilidades verificadas coincidentes: {len(required) + len(supported)}/{denominator}"
    if score < min_score:
        return Match("SKIPPED_INELIGIBLE", score, (explanation, "Compatibilidad inferior al umbral configurado"))
    return Match("MATCHED", score, ("Restricciones conocidas satisfechas", explanation))


def run_fixture(db: sqlite3.Connection, profile_id: str, provider: DiscoveryPort, *,
                dry_run: bool = True, min_score: float = 0.8) -> list[dict]:
    row = db.execute("SELECT preferences_json FROM professional_profiles WHERE id=? AND active=1",
                     (profile_id,)).fetchone()
    if row is None:
        raise ValueError("Active profile not found")
    criteria = ProfileCriteria.model_validate_json(row[0])
    # The preferences JSON cannot certify its own claims. Only persisted evidence
    # approved by the owner or supported by a document is eligible for matching.
    claims = db.execute("SELECT claim_json FROM knowledge_claims WHERE profile_id=? "
                        "AND claim_type='skill' AND verification_status IN "
                        "('master_confirmed','document_supported')", (profile_id,)).fetchall()
    verified = []
    for claim in claims:
        value = json.loads(claim[0])
        if isinstance(value, dict) and isinstance(value.get("value"), str):
            verified.append(value["value"])
    criteria = criteria.model_copy(update={"confirmed_claims": verified})
    candidates = provider.search()
    results = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        ats_provider = ("fixture" if provider.provider_name == "fixture" else
                        candidate.ats_provider or "manual") if candidate.ats_requisition_id else None
        key = ((ats_provider, candidate.ats_requisition_id) if candidate.ats_requisition_id
               else ("url", canonical_url(str(candidate.url))))
        if key in seen:
            results.append({"title": candidate.title, "status": "SKIPPED_DUPLICATE", "reasons": ["Mismo identificador"]})
            continue
        seen.add(key)
        match = evaluate(criteria, candidate, min_score=min_score)
        if provider.provider_name != "fixture" and match.status == "MATCHED":
            match = Match("MANUAL_REVIEW", match.score,
                          (*match.reasons, "El sitio y su política de automatización requieren revisión"))
        result = {"title": candidate.title, "status": match.status, "score": match.score,
                  "reasons": list(match.reasons)}
        if not dry_run:
            job_id, _ = save_job(db, Job(candidate.title, candidate.company, str(candidate.url),
                                       ats_provider, candidate.ats_requisition_id))
            application_id = str(uuid.uuid4())
            timestamp = now()
            with db:
                inserted = db.execute(
                    "INSERT OR IGNORE INTO applications (id,profile_id,job_posting_id,phase,status,"
                    "match_score,match_explanation_json,created_at,updated_at) VALUES (?,?,?,'DISCOVERY',?,?,?,?,?)",
                    (application_id, profile_id, job_id, match.status, match.score,
                     json.dumps(result["reasons"], ensure_ascii=False), timestamp, timestamp)).rowcount
                if inserted:
                    db.execute("INSERT INTO application_events (id,application_id,event_type,to_status,"
                               "actor_type,correlation_id,payload_redacted_json,created_at) "
                               "VALUES (?,?,'DISCOVERY_EVALUATED',?,'system',?,?,?)",
                               (str(uuid.uuid4()), application_id, match.status, str(uuid.uuid4()),
                                json.dumps({"reasons": result["reasons"]}, ensure_ascii=False), timestamp))
                else:
                    result["status"] = "SKIPPED_DUPLICATE"
                    result["reasons"] = ["La vacante ya existe para este perfil"]
            result["job_id"] = job_id
        results.append(result)
    return results
