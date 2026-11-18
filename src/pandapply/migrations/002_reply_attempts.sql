CREATE TABLE reply_attempts (
  id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL REFERENCES reply_proposals(id),
  idempotency_key TEXT NOT NULL UNIQUE,
  body_sha256 TEXT NOT NULL,
  attempt_status TEXT NOT NULL CHECK (attempt_status IN ('SENDING','SENT','UNKNOWN')),
  external_message_id TEXT,
  initiated_at TEXT NOT NULL,
  completed_at TEXT
);
CREATE INDEX reply_attempts_proposal ON reply_attempts(proposal_id);
