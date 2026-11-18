
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE master_profile (
  id TEXT PRIMARY KEY,
  display_name TEXT,
  timezone TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE professional_profiles (
  id TEXT PRIMARY KEY,
  master_id TEXT NOT NULL REFERENCES master_profile(id),
  name TEXT NOT NULL,
  preferences_json TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE knowledge_claims (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES professional_profiles(id),
  claim_type TEXT NOT NULL,
  claim_json TEXT NOT NULL,
  source_uri TEXT NOT NULL,
  source_hash TEXT,
  verification_status TEXT NOT NULL CHECK (verification_status IN ('master_confirmed','document_supported','unverified','disputed')),
  approval_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE documents (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES professional_profiles(id),
  kind TEXT NOT NULL CHECK (kind IN ('cv_original','cv_generated','cover_letter','other')),
  file_path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  source_document_ids_json TEXT NOT NULL DEFAULT '[]',
  claim_ids_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE TABLE search_runs (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES professional_profiles(id),
  search_provider TEXT NOT NULL,
  query_json TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  error_code TEXT
);
CREATE TABLE job_postings (
  id TEXT PRIMARY KEY,
  canonical_url TEXT,
  ats_provider TEXT,
  ats_requisition_id TEXT,
  fingerprint TEXT NOT NULL,
  title TEXT NOT NULL,
  company_name TEXT NOT NULL,
  location TEXT,
  description_text TEXT,
  source_url TEXT NOT NULL,
  discovered_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  UNIQUE(fingerprint)
);
CREATE UNIQUE INDEX job_posting_ats_unique
  ON job_postings(ats_provider, ats_requisition_id)
  WHERE ats_provider IS NOT NULL AND ats_requisition_id IS NOT NULL;
CREATE TABLE applications (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES professional_profiles(id),
  job_posting_id TEXT NOT NULL REFERENCES job_postings(id),
  phase TEXT NOT NULL,
  status TEXT NOT NULL,
  match_score REAL,
  match_explanation_json TEXT,
  policy_version TEXT,
  selected_cv_id TEXT REFERENCES documents(id),
  cover_letter_id TEXT REFERENCES documents(id),
  applied_at TEXT,
  receipt_uri TEXT,
  receipt_ref TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  UNIQUE(profile_id, job_posting_id)
);
CREATE TABLE submission_attempts (
  id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL REFERENCES applications(id),
  idempotency_key TEXT NOT NULL UNIQUE,
  permit_json TEXT NOT NULL,
  attempt_status TEXT NOT NULL CHECK (attempt_status IN ('PREPARED','SUBMITTING','CONFIRMED','UNKNOWN','FAILED_PRE_CLICK')),
  external_receipt TEXT,
  initiated_at TEXT NOT NULL,
  completed_at TEXT
);
CREATE TABLE mailbox_messages (
  id TEXT PRIMARY KEY,
  gmail_account_id TEXT NOT NULL,
  gmail_message_id TEXT NOT NULL,
  gmail_thread_id TEXT NOT NULL,
  sender TEXT,
  subject_redacted TEXT,
  sent_at TEXT NOT NULL,
  classification TEXT,
  confidence REAL,
  application_id TEXT REFERENCES applications(id),
  correlation_confidence REAL,
  processed_at TEXT,
  UNIQUE(gmail_account_id, gmail_message_id)
);
CREATE TABLE gmail_cursors (
  gmail_account_id TEXT PRIMARY KEY,
  last_history_id TEXT,
  last_poll_at TEXT,
  overlap_start_at TEXT
);
CREATE TABLE reply_proposals (
  id TEXT PRIMARY KEY,
  mailbox_message_id TEXT NOT NULL REFERENCES mailbox_messages(id),
  recipient TEXT NOT NULL,
  text_body TEXT NOT NULL,
  text_sha256 TEXT NOT NULL,
  state TEXT NOT NULL,
  approved_by_decision_id TEXT,
  sent_gmail_message_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE master_decisions (
  id TEXT PRIMARY KEY,
  decision_type TEXT NOT NULL,
  related_entity_type TEXT NOT NULL,
  related_entity_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  decision_status TEXT NOT NULL CHECK (decision_status IN ('PENDING','APPROVED','REJECTED','EXPIRED','CANCELLED')),
  authorized_channel TEXT,
  authorized_principal TEXT,
  decided_at TEXT,
  expires_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE application_events (
  id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL REFERENCES applications(id),
  event_type TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT,
  actor_type TEXT NOT NULL,
  actor_id TEXT,
  correlation_id TEXT NOT NULL,
  evidence_ref TEXT,
  payload_redacted_json TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE job_locks (
  key TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  locked_until TEXT NOT NULL,
  heartbeat_at TEXT NOT NULL
);
CREATE TABLE event_outbox (
  id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  payload_redacted_json TEXT NOT NULL,
  destination TEXT NOT NULL,
  delivery_status TEXT NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  delivered_at TEXT
);
CREATE TABLE connector_health (
  connector_id TEXT PRIMARY KEY,
  state TEXT NOT NULL,
  checked_at TEXT NOT NULL,
  detail_redacted TEXT
);

CREATE INDEX applications_status_updated ON applications(status, updated_at);
CREATE INDEX mailbox_thread ON mailbox_messages(gmail_thread_id);
CREATE INDEX application_events_history ON application_events(application_id, created_at);
