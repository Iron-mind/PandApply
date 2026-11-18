CREATE TABLE config_revisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  config_json TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  actor TEXT NOT NULL,
  created_at TEXT NOT NULL
);
