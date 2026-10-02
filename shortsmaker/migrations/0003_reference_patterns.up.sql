-- REFERENCE LAB: 참고 영상에서 뽑은 '추상 패턴'만 저장한다 (원본 대사/자막/영상 파일은 저장하지 않는다).
CREATE TABLE IF NOT EXISTS reference_patterns (
  id TEXT PRIMARY KEY,
  platform TEXT, source_ref TEXT, category TEXT,
  status TEXT,                  -- VERIFIED | PARTIAL | UNVERIFIED
  saved INTEGER DEFAULT 0,      -- 0 = 분석 초안, 1 = 라이브러리에 저장
  library_tags TEXT,            -- JSON ["PROBLEM_STORY", ...]
  pattern_json TEXT,            -- 추상 패턴 (vocab 값/숫자만)
  scores_json TEXT,
  confidence REAL,
  fingerprint_json TEXT,        -- 원문 복사 방지용 해시 (원문을 복원할 수 없는 4자 조각 해시)
  rights TEXT,                  -- 업로드 영상의 권한 표시 (LICENSED_REMIX 대상 여부): NONE | OWNED | LICENSED
  created_at TEXT
);
