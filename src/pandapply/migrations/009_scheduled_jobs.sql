CREATE TABLE scheduled_jobs (
  name TEXT PRIMARY KEY,
  hermes_home TEXT NOT NULL,
  hermes_executable TEXT NOT NULL,
  hermes_job_id TEXT,
  schedule TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('CREATING','PAUSED','ACTIVE','UNKNOWN')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
