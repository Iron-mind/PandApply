CREATE TABLE reply_dispatches (
  attempt_id TEXT PRIMARY KEY REFERENCES reply_attempts(id),
  claimed_at TEXT NOT NULL
);
