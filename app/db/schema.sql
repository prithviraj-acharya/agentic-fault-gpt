CREATE TABLE IF NOT EXISTS tickets (
  ticket_id TEXT PRIMARY KEY,
  ticket_ref TEXT UNIQUE,
  ahu_id TEXT NOT NULL,
  incident_key TEXT NOT NULL,
  detected_fault_type TEXT NOT NULL,
  lifecycle_status TEXT NOT NULL,
  diagnosis_status TEXT NOT NULL,
  confidence REAL,
  occurrence_count INTEGER NOT NULL DEFAULT 0,
  diagnosis_title TEXT,
  root_cause TEXT,
  recommended_actions TEXT,
  evidence_ids TEXT NOT NULL DEFAULT '[]',
  review_status TEXT NOT NULL DEFAULT 'NONE',
  review_notes TEXT,
  symptom_summary TEXT,
  window_refs TEXT NOT NULL DEFAULT '[]',
  signatures_seen TEXT NOT NULL DEFAULT '[]',
  last_window_id TEXT,
  last_window_end_ts INTEGER,
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  diagnosed_at TEXT,
  resolved_at TEXT,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tickets_incident_open
  ON tickets(incident_key, lifecycle_status);

CREATE INDEX IF NOT EXISTS idx_tickets_ahu
  ON tickets(ahu_id);

CREATE INDEX IF NOT EXISTS idx_tickets_review
  ON tickets(review_status);
