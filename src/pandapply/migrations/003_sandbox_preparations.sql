CREATE TABLE sandbox_preparations (
  application_id TEXT PRIMARY KEY REFERENCES applications(id),
  document_id TEXT NOT NULL REFERENCES documents(id),
  form_fingerprint TEXT NOT NULL,
  created_at TEXT NOT NULL
);
