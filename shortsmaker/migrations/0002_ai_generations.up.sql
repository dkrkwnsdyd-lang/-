-- AI 장면 생성 기록 (비용/재시도/캐시/상품 일치 검사). 기존 테이블은 건드리지 않는다.
CREATE TABLE IF NOT EXISTS ai_generations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT, scene_id TEXT,
  generation_mode TEXT, cost_mode TEXT, actor_mode TEXT,
  source_type TEXT, provider TEXT, model TEXT,
  prompt TEXT, cache_key TEXT,
  generation_cost REAL,            -- NULL = 비용 확인 불가 (임의 숫자를 넣지 않는다)
  seconds REAL,
  generation_status TEXT,          -- PLANNED | GENERATED | CACHED | FAILED | PROVIDER_UNAVAILABLE | SKIPPED
  retry_count INTEGER DEFAULT 0,
  product_fidelity_status TEXT,    -- PASS | PRODUCT_MISMATCH | UNVERIFIED | NOT_APPLICABLE
  error TEXT,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_gen_key ON ai_generations(cache_key);
