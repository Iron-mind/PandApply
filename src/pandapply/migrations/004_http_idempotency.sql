CREATE TABLE http_idempotency (
  key TEXT NOT NULL,
  scope TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  response_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (scope, key)
);
