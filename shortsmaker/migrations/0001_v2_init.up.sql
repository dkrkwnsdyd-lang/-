-- SHOP SHORTS V2 초기 스키마 (기존 데이터 없음 - 새 테이블만 생성)
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  mode TEXT NOT NULL,
  status TEXT NOT NULL,
  product_name TEXT,
  input_json TEXT,
  result_json TEXT,
  total_cost REAL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id),
  step TEXT NOT NULL,
  status TEXT NOT NULL,          -- PENDING RUNNING SUCCESS FAILED RETRY
  attempt INTEGER DEFAULT 0,
  detail TEXT,
  started_at TEXT,
  finished_at TEXT
);
CREATE TABLE IF NOT EXISTS costs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT,
  provider TEXT, model TEXT, task TEXT,
  input_usage REAL, output_usage REAL,
  estimated_cost REAL, duration REAL,
  timestamp TEXT
);
CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT, path TEXT, kind TEXT,
  rights TEXT NOT NULL DEFAULT 'UNKNOWN',
  source TEXT
);
CREATE TABLE IF NOT EXISTS qa_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT, stage TEXT, target TEXT,
  scores_json TEXT, passed INTEGER, notes TEXT, timestamp TEXT
);
CREATE TABLE IF NOT EXISTS references_ (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT, status TEXT, analysis_json TEXT, timestamp TEXT
);
CREATE TABLE IF NOT EXISTS performance (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT, platform TEXT, post_url TEXT,
  views INTEGER, retention_3s REAL, avg_view_duration REAL, completion_rate REAL,
  likes INTEGER, comments INTEGER, shares INTEGER, saves INTEGER, ctr REAL,
  affiliate_clicks INTEGER, conversion REAL,
  hook_type TEXT, story_pattern TEXT, selling_angle TEXT, video_length REAL,
  scene_pattern TEXT, cta TEXT, recorded_at TEXT
);
