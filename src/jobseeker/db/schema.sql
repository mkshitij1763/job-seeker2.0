CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  google_sub TEXT UNIQUE,
  email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  is_admin INTEGER NOT NULL DEFAULT 0,
  disabled_at TEXT,
  created_at TEXT NOT NULL,
  last_login_at TEXT,
  notified_on TEXT,
  outreach_enabled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS invites (
  email TEXT PRIMARY KEY,
  invited_by INTEGER REFERENCES users (id),
  created_at TEXT NOT NULL,
  accepted_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users (id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id);
CREATE TABLE IF NOT EXISTS user_jobs (
  user_id INTEGER NOT NULL REFERENCES users (id),
  job_id INTEGER NOT NULL REFERENCES jobs (id),
  filter_reason TEXT,
  prescore INTEGER,
  jd_hash TEXT NOT NULL,
  evaluated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, job_id)
);
CREATE INDEX IF NOT EXISTS idx_user_jobs_open ON user_jobs (user_id, filter_reason);

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
  user_id INTEGER NOT NULL REFERENCES users (id),
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
  created_at TEXT NOT NULL,
  profile_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_scores_user_job ON scores (user_id, job_id, id);

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
  notes TEXT NOT NULL DEFAULT '',
  owner_user_id INTEGER REFERENCES users (id)  -- NULL: the shared cache; set: that user's private row
);
CREATE INDEX IF NOT EXISTS idx_contacts_owner ON contacts (owner_user_id);

CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users (id),
  job_id INTEGER NOT NULL REFERENCES jobs (id),
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
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, job_id)
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
  user_id INTEGER NOT NULL REFERENCES users (id),
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
  errors TEXT NOT NULL DEFAULT '[]',
  user_id INTEGER REFERENCES users (id),
  kind TEXT NOT NULL DEFAULT 'legacy',
  trigger TEXT NOT NULL DEFAULT 'cli',
  parent_id INTEGER REFERENCES runs (id)
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
  nudged_at TEXT,
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
  user_id INTEGER NOT NULL REFERENCES users (id),
  period TEXT NOT NULL,
  service TEXT NOT NULL,
  amount REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, period, service)
);
CREATE TABLE IF NOT EXISTS user_prefs (
  user_id INTEGER PRIMARY KEY REFERENCES users (id),
  data TEXT NOT NULL,
  version INTEGER NOT NULL,
  onboarding_step TEXT,
  onboarded_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_facts (
  user_id INTEGER PRIMARY KEY REFERENCES users (id),
  resume_sha256 TEXT,
  facts TEXT,
  edited INTEGER NOT NULL DEFAULT 0,
  extract_status TEXT NOT NULL DEFAULT 'idle' CHECK (extract_status IN ('idle', 'running', 'done', 'failed')),
  extract_error TEXT NOT NULL DEFAULT '',
  extract_started_at TEXT,
  resume_uploaded_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS push_subscriptions (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  endpoint TEXT NOT NULL UNIQUE,
  p256dh TEXT NOT NULL,
  auth TEXT NOT NULL,
  user_agent TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  last_success_at TEXT,
  failures INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_push_subscriptions_user ON push_subscriptions (user_id);
CREATE TABLE IF NOT EXISTS backups (
  day TEXT PRIMARY KEY,
  local_path TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  uploaded_at TEXT,
  upload_error TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS locks (
  name TEXT PRIMARY KEY,
  holder TEXT NOT NULL,
  acquired_at TEXT NOT NULL,
  heartbeat_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_requests (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users (id),
  requested_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'done', 'failed')),
  run_id INTEGER REFERENCES runs (id),
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_run_requests_status ON run_requests (status, requested_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_run_requests_one_pending ON run_requests (user_id)
  WHERE status IN ('queued', 'running');
CREATE INDEX IF NOT EXISTS idx_runs_kind ON runs (kind, trigger, started_at);
CREATE TABLE IF NOT EXISTS people_searches (
  company_norm TEXT NOT NULL,
  query TEXT NOT NULL,
  provider TEXT NOT NULL,
  results TEXT NOT NULL,
  searched_at TEXT NOT NULL,
  PRIMARY KEY (company_norm, query, provider)
);
CREATE TABLE IF NOT EXISTS gmail_tokens (
  user_id INTEGER PRIMARY KEY REFERENCES users (id),
  account_email TEXT NOT NULL,
  token_enc BLOB NOT NULL,
  status TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'expired')),
  connected_at TEXT NOT NULL,
  refreshed_at TEXT
);
CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, checked_at TEXT NOT NULL);
