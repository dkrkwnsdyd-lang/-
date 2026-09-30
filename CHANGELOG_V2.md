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

- 물티슈 실사진 반영: `product_short` 수량 토큰 제외, 확대 컷 최소 해상도(`MIN_ZOOM_SIDE=900`), benefit 은 사용 장면 사진 고정, 사용자 박스가 배경 제거 결과도 자름, 문제/근거 없을 때 자막(`rule_director`), '유아' 카테고리

- 플랫폼 문구: 숫자/수식어 해시태그 제거 + 브랜드 태그, 유튜브 제목·쓰레드 본문 중복 제거 (`adapter._tags`, `platform_copy`)

- 직접 촬영 사진 테스트 반영: 특징-사진 연결 `ProductInput.feature_photos` / CLI `--feature-photo` / `Scene.ref_locked`, 디자인 키워드에서 색상 제외(근거 없는 장점 방지), 해시태그 기호 제거

- Added: 웹 스튜디오 '특징이 보이는 사진 연결' (`studio.html` featureLink → `studio_api.create_job` `feature_photos`). CLI `--feature-photo` 와 동일 기능

- Provider: 환경 '자격 증명'(프록시가 키를 붙여줌) 자동 감지 (`Provider._probe_proxy_credential`, `auth_headers`, `auth_state`) — Gemini 는 키 환경 변수 없이도 동작

- Added: `studio/vision.py` Vision 분석(제품 위치 박스, 특징-사진 연결, 개인정보 요소 경고), 파이프라인 연결(사용자 지정 우선, 실패 시 수동값으로 계속)
- Modified: 모델 레지스트리 gemini-2.5-* → gemini-3.8-flash / 3.1-flash-lite (2.5 는 신규 사용자 404). 결제/인증/모델없음 오류는 재시도 없이 다음 provider, 결제·인증 오류 provider 는 작업 중 건너뜀 (`ProviderError.retryable`, `Router.dead`)

- Added: `studio/grounding.py` 근거 검증 (allowed_facts, LLM 판정, 피드백 재생성, 규칙 폴백) — 대본(`director.llm_director`)과 플랫폼 문구(`adapter.platform_copy`)에 적용, 문제 입력 없으면 problem 장면 제거(`_enforce_problem_rule`)
- Added: 개인정보 사진은 박스 없으면 영상에서 제외, 박스가 있으면 타이트 크롭 (`PlateCache.tight`, pipeline)
- Modified: Vision/판정 호출 temperature 0, 박스 누락 시 1회 재시도, 특징 연결 문장 겹침 매칭(`director._linked_photo`), Vision 최종 평가 점수 기준표 명시

- Added (모바일/앱): PWA(`web/static/manifest.webmanifest`, `sw.js`, `icons/*`), 모바일 화면 개편(`studio.html`: 카메라 촬영, 앨범, 하단 고정 버튼, 공유 시트로 영상 공유, 문구 복사, 최근 작업, 새로고침해도 진행 중 작업 이어보기, 화면 꺼짐 방지, 설치 안내), 접근 암호(`web/auth.py`: 쿠키/Bearer, 로그인 5회/분 제한, 외부에 열면 암호 자동 생성), 아이폰 HEIC 지원, 업로드 제한(12장/30MB), `Dockerfile`/`docker-compose.yml`/`.dockerignore`, `MOBILE.md`
- Modified: `shortsmaker web --host 0.0.0.0 --access-code`, `/healthz`, `/favicon.ico`

- Added (문구 톤): 플랫폼 게시 문구를 광고체가 아닌 친구에게 말하는 대화체로 (`adapter.VOICE`: 공감→포인트→디테일→마무리, 짧은 줄, 이모지 1~2개), 대체 템플릿도 대화체 (`adapter._casual_post`)
- Added: '내가 직접 써본 느낌 한 줄' 입력 (`ProductInput.my_take`, 웹 `myTake`, API `my_take`). 경험담(써보니/했더니)은 이 한 줄만 근거로 허용, 없으면 사진에 보이는 것/특징만 (`grounding.RULES_FOR_WRITER`, `allowed_facts`). 실호출 검증: 지어낸 경험 문장은 판정기가 걸러냄

- Added (Windows): `install.bat`(가상환경/부품/.env), `start.bat`(포트 검사, git pull, 접근 암호 확인, tailscale serve, 브라우저 열기, 서버 실행), `.gitattributes`(*.bat CRLF), MOBILE.md 안내. 실제 Windows 실행 검증은 사용자 PC 에서 필요

- Added (영상 클립 1단계): 직접 찍은 상품 영상 업로드(`videos`, 최대 4개/200MB, mp4·mov·m4v·webm·mkv·3gp). `studio/clips.py`: 3fps 분석(선명도/밝기/흔들림) → 컷 길이에 맞는 최적 구간 선택(겹침 방지), demo/benefit/detail/reveal 컷을 `video_clip` 으로 교체(최대 3컷, 컷 길이/자막/오디오 타이밍 유지), 세로는 꽉 채움·가로는 흐린 배경 위 배치, 원본 소리 미사용, 대표 프레임 Vision 개인정보 검사(걸리면 클립 제외, 검사 불가 시 경고). `motion.Shot.clip_start/clip_aspect`, `MotionRenderer._clip_frame/close_clips`, 화면 '🎬 영상 클립 추가'

### Known Issues
- 외부 AI(LLM/TTS/영상 생성) 실호출 미검증 — 키 없음 + 샌드박스 네트워크 차단
- 사람/손이 나오는 실제 사용 장면은 영상 생성 provider 연결 전까지 만들 수 없음 (현재는 원본 사진 모션)
- 로컬 Final QA 는 측정 지표 기반이라 "장면-자막 의미 일치", "고급스러움" 같은 사람 판단은 못 함 → Vision LLM 연결 필요
- 테스트 상품이 합성 이미지 (실사진 1장만 사용)
