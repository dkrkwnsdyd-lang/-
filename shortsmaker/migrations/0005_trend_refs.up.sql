-- 트렌드 레퍼런스: 브라우저 확장(레퍼런스 인사이트)에서 보낸 "링크 + 공개 숫자"만 저장한다. 본문·영상·이미지는 저장하지 않는다.
CREATE TABLE IF NOT EXISTS trend_refs (
  id TEXT PRIMARY KEY,          -- platform:원본ID
  platform TEXT,                -- xiaohongshu | youtube | instagram | tiktok | threads
  source_id TEXT,
  url TEXT,
  title TEXT,
  author TEXT,
  likes INTEGER,
  collects INTEGER,
  comments INTEGER,
  mult REAL,                    -- 목록 중앙값 대비 성과배수
  score INTEGER,                -- 반응점수 0~100
  tier TEXT,
  context TEXT,                 -- 찾은 곳 (검색어 등)
  saved_at TEXT,                -- 확장에서 저장한 시각
  imported_at TEXT,
  updated_at TEXT
);
