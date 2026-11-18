CREATE TABLE mail_review_queue (
  gmail_account_id TEXT NOT NULL,
  gmail_message_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'PENDING' CHECK (state IN ('PENDING','DISMISSED')),
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY (gmail_account_id, gmail_message_id)
);
