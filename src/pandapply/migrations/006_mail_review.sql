CREATE TABLE mail_review_evidence (
  message_id TEXT PRIMARY KEY REFERENCES mailbox_messages(id),
  application_id TEXT NOT NULL REFERENCES applications(id),
  decision_id TEXT NOT NULL UNIQUE REFERENCES master_decisions(id),
  content_sha256 TEXT NOT NULL,
  proposed_classification TEXT NOT NULL,
  prior_application_status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
