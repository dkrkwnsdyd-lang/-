-- UGC Reference Mode: 레퍼런스 분석 결과(구조화 JSON)와 작업 세션(콘셉트/스토리보드/프롬프트 패키지). 기존 테이블은 건드리지 않는다.
CREATE TABLE IF NOT EXISTS ugc_references (
  id TEXT PRIMARY KEY,
  source_kind TEXT,             -- upload | youtube_url | notes
  source_ref TEXT,              -- 파일 이름 또는 URL (원본 영상 파일은 저장하지 않는다)
  status TEXT,                  -- VERIFIED | PARTIAL | FAILED
  analysis_json TEXT,           -- referenceAnalysis (구조화)
  fingerprint_json TEXT,        -- 원문 복제 방지 해시
  error TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS ugc_sessions (
  id TEXT PRIMARY KEY,
  product_json TEXT,
  reference_ids TEXT,
  mixer_json TEXT,
  concepts_json TEXT,
  selected_concept TEXT,
  storyboard_json TEXT,
  package_json TEXT,
  created_at TEXT,
  updated_at TEXT
);
