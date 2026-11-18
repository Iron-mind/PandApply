CREATE TABLE site_policy_reviews (
  id TEXT PRIMARY KEY,
  domain TEXT NOT NULL,
  operation TEXT NOT NULL CHECK (operation IN ('discover','read','fill','submit')),
  disposition TEXT NOT NULL CHECK (disposition IN ('ALLOWED','MANUAL_ONLY','BLOCKED')),
  source_url TEXT NOT NULL,
  rationale TEXT NOT NULL,
  reviewer TEXT NOT NULL,
  reviewed_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX site_policy_latest ON site_policy_reviews(domain, operation, reviewed_at);
CREATE TABLE site_policy_consents (
  policy_id TEXT PRIMARY KEY REFERENCES site_policy_reviews(id),
  principal TEXT NOT NULL,
  created_at TEXT NOT NULL,
  revoked_at TEXT
);
