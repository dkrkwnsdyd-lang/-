# CHANGELOG_V2

## 2026-09-28 — V2 1차 (Audit + API V2 + Scene Director V2 + Product Lock + QA + Compliance)

### Added
- `shortsmaker/brain/` SHORTS BRAIN: SYSTEM RULES(`system/*.yaml` 12개), 정책(`policy/*.yaml`: common, korea, youtube, instagram, tiktok, threads), LEARNED KNOWLEDGE(`data/brain/*.json`, UNVERIFIED 저장 거부)
- `shortsmaker/providers/`: Provider 추상화(`base.py`), OpenAI/Gemini/Groq(`llm.py`), ElevenLabs/Pexels/Pixabay/영상 생성 자리(`media.py`), MODEL REGISTRY(`model_registry.yaml`), Router(재시도·폴백·비용·상태 기록·Control Center)
- `shortsmaker/db.py` + `shortsmaker/migrations/0001_v2_init.{up,down}.sql`: jobs, job_steps(JOB QUEUE), costs, assets(RIGHTS), qa_results, references_, performance
- `shortsmaker/studio/product.py`: ProductInput, URL 공개 메타데이터 import, 사진 분석(UNKNOWN 원칙), PRODUCT LOCK(ProductIdentity), 배경 제거(cutout)
- `shortsmaker/studio/director.py`: Selling Angle, Story Director(10 패턴), Hook(3 후보), Script, Scene Director V2(20개 필드), 길이 자동 결정, First/End frame 서술
- `shortsmaker/studio/motion.py`: High Quality Image Motion 렌더러(샷 10종, 스튜디오 배경, 그림자, 라이트 스윕, 패럴랙스, 랙 포커스, 휩/플래시 전환, 펀치 줌, 다이내믹 자막)
- `shortsmaker/studio/editor.py`: AI Editor(첫 3초 규칙, 긴 장면 분할, 박자 맞춤 컷, 강조=펀치 줌 동기화, SFX 배치)
- `shortsmaker/studio/audio.py`: 효과음 합성, 저작권 없는 음악 베드, 보이스 덕킹, 믹스
- `shortsmaker/studio/qa.py`: Storyboard Visual QA, Multi Take / Best Take Selector, Final Video QA(측정 기반) + Vision LLM 보조
- `shortsmaker/studio/compliance.py`: PRODUCT/CONTENT/CLAIM/DISCLOSURE/RIGHTS 게이트, 플랫폼별 판정
- `shortsmaker/studio/adapter.py`: 플랫폼별 문구, 플랫폼별 CTA 장면, LUFS 정규화 export
- `shortsmaker/studio/reference.py`: Reference Miner(로컬 mp4 컷 분석=PARTIAL, YouTube URL=Gemini, 불가=UNVERIFIED)
- `shortsmaker/studio/tts.py`, `shortsmaker/studio/pipeline.py`(전체 오케스트레이션, 장면 재시도, 최종 QA 수리 루프)
- `shortsmaker/web/studio_api.py`, `web/static/studio.html`(기본 화면), `web/static/control.html`(API Control Center)
- CLI: `studio`, `api-status`, `db-rollback`
- `.env.example`, `.env` 로딩(`config.load_dotenv`)
- 상태 파일: PROJECT_STATUS.md, NEXT_TASKS.md, API_STATUS.md, CHANGELOG_V2.md, TEST_RESULTS.md
- 테스트: `tests/test_v2.py`(21), `tests/product_fixtures.py`(합성 제품 5종), `tests/test_web.py` V2 항목

### Modified
- `shortsmaker/web/app.py`: `/` 가 V2 스튜디오, 기존 화면은 `/classic`, `/control` 추가
- `shortsmaker/cli.py`: V2 명령 추가 (기존 make/publish/auto/web 유지)
- `shortsmaker/config.py`: .env 로딩
- `.gitignore`: `.env`, `data/`

### Removed
- 없음 (기존 V1 기능 그대로 유지)

### Migrated
- SQLite `data/shorts.db` 에 `0001_v2_init` (새 테이블만 생성, 되돌리기: `python -m shortsmaker db-rollback`)

### Fixed
- 자막: 긴 강조 구절이 화면 밖으로 넘치던 문제 → 단어 단위 분리 + 안전영역 폭 자동 맞춤
- 자막: 문장부호가 떨어져 보이던 문제, 단어 간격이 외곽선에 묻히던 문제
- 훅: 첫 컷이 제품을 과하게 확대하던 문제 (punch_in 배율 축소, take 선택 시 스토리 적합도 가중)
- 제품 공개가 5.1초로 늦던 문제 → hook 1.8s + problem 1.5s 고정, 공개 이후 장면만 길이 보정
- Product Lock: 흰 제품+밝은 배경에서 배경 제거가 제품을 지우던 문제 → `product.cutout_reliability` 로 거부
- Final QA 변별력: 실제 MP4 컷별 화면 비교(반복/단조로움) 추가 (`qa._similar`, `qa._distinct_looks`)
- 수리 루프: 원인별 장면 수리(`pipeline._repair` + `repair_hints`), 저해상도 시 확대 샷 제외로 진동 방지
- PHOTO ONLY: 정보 없을 때 '궁금증→공개' 구조 (`director.mystery_director`), 디렉터 샷 힌트 우선
- 훅 문장 끝부분 추출(`director.tail_phrase`), COMPARISON 오판정, Threads 문구 어색함

- 훅: '진짜 되는지 보세요'는 시험 가능한 제품(강도/충전/세척 등)에만, 그 외는 discovery 훅 (`director.TESTABLE_KEYWORDS`)

- 실사진 테스트 반영: 복잡한 배경 사진은 확대 컷 금지(`director.zoomable`, `qa.storyboard_qa`, `editor` 분할 컷), 원본 카드 확대 + 제품 중심 3:4 크롭(`motion._hero_parts`, `PlateCache.product_region`), 배경 블러 개선
- Added: 제품 위치 박스 `ProductInput.product_boxes` / CLI `--box` (Vision LLM 이 채울 자리)

- Added: 웹 스튜디오에서 사진을 눌러 제품 위치를 드래그로 지정 (`studio.html` boxes → `studio_api.create_job` → `product_boxes`). 이미지 끌어가기 때문에 드래그가 끊기던 버그 수정

### Known Issues
- 외부 AI(LLM/TTS/영상 생성) 실호출 미검증 — 키 없음 + 샌드박스 네트워크 차단
- 사람/손이 나오는 실제 사용 장면은 영상 생성 provider 연결 전까지 만들 수 없음 (현재는 원본 사진 모션)
- 로컬 Final QA 는 측정 지표 기반이라 "장면-자막 의미 일치", "고급스러움" 같은 사람 판단은 못 함 → Vision LLM 연결 필요
- 테스트 상품이 합성 이미지 (실사진 1장만 사용)
