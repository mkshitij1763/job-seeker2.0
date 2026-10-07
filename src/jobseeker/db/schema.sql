CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  source_job_id TEXT NOT NULL,
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  location TEXT NOT NULL DEFAULT '',
  location_city TEXT,
  remote INTEGER NOT NULL DEFAULT 0,
  posted_at TEXT,
  salary_text TEXT,
  jd_text TEXT NOT NULL DEFAULT '',
  jd_hash TEXT NOT NULL,
  apply_url TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  alt_urls TEXT NOT NULL DEFAULT '[]',
  filter_reason TEXT,
  prescore INTEGER,
  jd_attempts INTEGER NOT NULL DEFAULT 0,
  first_seen_at TEXT NOT NULL,
  UNIQUE (source, source_job_id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs (fingerprint);

CREATE TABLE IF NOT EXISTS scores (
  id INTEGER PRIMARY KEY,
  job_id INTEGER NOT NULL REFERENCES jobs (id),
  score INTEGER NOT NULL,
  breakdown TEXT NOT NULL,
  matches TEXT NOT NULL,
  gaps TEXT NOT NULL,
  recommendation TEXT NOT NULL,
  role_family TEXT NOT NULL,
  model TEXT NOT NULL,
  rubric_version TEXT NOT NULL,
  jd_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scores_job ON scores (job_id);

CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY,
  company TEXT NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT '',
  linkedin_url TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  email_status TEXT NOT NULL DEFAULT 'unverified'
    CHECK (email_status IN ('unverified', 'verified', 'bounced')),
  source TEXT NOT NULL DEFAULT 'manual',
  notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY,
  job_id INTEGER NOT NULL UNIQUE REFERENCES jobs (id),
  contact_id INTEGER REFERENCES contacts (id),
  status TEXT NOT NULL DEFAULT 'new',
  snoozed_until TEXT,
  snoozed_from TEXT,
  applied_via_portal INTEGER NOT NULL DEFAULT 0,
  followups_sent INTEGER NOT NULL DEFAULT 0,
  notes TEXT NOT NULL DEFAULT '',
  suggested_contact_role TEXT NOT NULL DEFAULT '',
  suggested_contact_reason TEXT NOT NULL DEFAULT '',
  linkedin_search_url TEXT NOT NULL DEFAULT '',
  draft_warnings TEXT NOT NULL DEFAULT '[]',
  find_status TEXT NOT NULL DEFAULT 'idle',
  find_error TEXT NOT NULL DEFAULT '',
  find_started_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drafts (
  id INTEGER PRIMARY KEY,
  application_id INTEGER NOT NULL REFERENCES applications (id),
  kind TEXT NOT NULL CHECK (kind IN ('email', 'li_note', 'li_dm')),
  subject TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL,
  edited INTEGER NOT NULL DEFAULT 0,
  gmail_draft_id TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (application_id, kind)
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  application_id INTEGER NOT NULL REFERENCES applications (id),
  at TEXT NOT NULL,
  type TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_app ON events (application_id);

CREATE TABLE IF NOT EXISTS blocklist (
  id INTEGER PRIMARY KEY,
  contact_id INTEGER REFERENCES contacts (id),
  company TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  stats TEXT NOT NULL DEFAULT '{}',
  errors TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS discovered_companies (
  id INTEGER PRIMARY KEY,
  name_norm TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  ats TEXT,
  slug TEXT,
  status TEXT NOT NULL CHECK (status IN ('active', 'none', 'inactive')),
  checked_at TEXT NOT NULL,
  jobs_seen INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS application_contacts (
  id INTEGER PRIMARY KEY,
  application_id INTEGER NOT NULL REFERENCES applications (id),
  contact_id INTEGER NOT NULL REFERENCES contacts (id),
  rank INTEGER NOT NULL CHECK (rank BETWEEN 1 AND 3),
  label TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  wave INTEGER NOT NULL DEFAULT 1,
  email_source TEXT NOT NULL DEFAULT '',
  gmail_draft_id TEXT,
  emailed_at TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (application_id, rank)
);

CREATE TABLE IF NOT EXISTS contact_candidates (
  id INTEGER PRIMARY KEY,
  application_id INTEGER NOT NULL REFERENCES applications (id),
  position INTEGER NOT NULL,
  name TEXT NOT NULL,
  headline TEXT NOT NULL DEFAULT '',
  linkedin_url TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  used INTEGER NOT NULL DEFAULT 0,
  UNIQUE (application_id, position)
);

CREATE TABLE IF NOT EXISTS company_domains (
  name_norm TEXT PRIMARY KEY,
  domain TEXT,
  pattern TEXT,
  catch_all INTEGER,
  mx_host TEXT,
  checked_at TEXT NOT NULL,
  catch_all_at TEXT
);

CREATE TABLE IF NOT EXISTS usage (
  period TEXT NOT NULL,
  service TEXT NOT NULL,
  amount REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (period, service)
);
