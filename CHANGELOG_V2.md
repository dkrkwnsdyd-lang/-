# CHANGELOG_V2

## 2026-10-03 — UGC Reference Mode (선택 기능, 기본 OFF)
- `studio/ugc_reference/`: schema, analyzer(업로드 영상/YouTube/메모 → 구조화 JSON, 실패해도 예외 없음), mixer(연출 원리만 채택·상품에 안 맞으면 기각+이유), concepts(문제해결/사용체험/발견 3개), storyboard(3~5초 장면), prompts(영상 프롬프트와 대사/자막/SFX 분리, provider 무관 Prompt Package), service(DB 저장·선택·장면 수정), connect(기존 영상 엔진 연결)
- DB 마이그레이션 `0004_ugc_reference`(테이블 2개 추가, 기존 데이터 변경 없음). API `/api/v2/ugc/*` 8개, form `ugc_session_id`
- 파이프라인: 세션이 있으면 director_data/장면 프롬프트만 주입(AI 장면 비용 제어·동의 규칙은 그대로). OFF 에서는 UGC 모듈을 import 하지 않음(테스트로 확인)
- 사실 안전: "써봤다" 류 표현은 my_take/검증된 후기가 있을 때만(사용 체험형은 설명/시연형으로 대체), 원본 영상·문장은 저장하지 않음

## 2026-10-03 — 쿠팡 파트너스 API (정보 전용)
- `studio/coupang.py`, CLI `coupang-check`/`coupang-search`, `GET /api/v2/coupang/search`, 상품명 옆 '쿠팡에서 상품 정보 찾기'. 이미지 미사용, 가격 24시간 신선도, `ProductInput.price_meta`

## 2026-10-02 — REFERENCE_VIDEO_ENGINE
- `studio/reference_engine/`: vocab(어휘), platforms, analyzer, patterns(추상 패턴·점수·라이브러리 태그), fingerprint(원문 복제 방지 해시), library(DB), mix(AUTO/수동 조합), apply(상품 적응·가이드·템포/전환 적용), remix(Licensed Remix 권한 검문)
- DB 마이그레이션 `0003_reference_patterns` (기존 데이터 변경 없음). 원문/영상은 저장하지 않고 패턴 값 + 해시만 저장
- 전략 엔진: 패턴의 스토리 단계(situation/pain/pain_emotion/turning/…)로 대본 구조 변경, Hook 유형/CTA 방식 선호, 감사 시 늦은 공개 허용, 복제/번역투 차단(line_issues), 반복 CTA 교체
- Storyboard: `story_role`, 템포/Hook 길이/전환/모션/자막 위치 적용(최소 12초 보장), `production.reference` 에 적용 결과
- API/UI: REFERENCE LAB(분석·저장·조합·이 패턴으로 영상 제작), `POST /api/v2/reference/{analyze,mix}`, `GET/POST/DELETE /reference/patterns`

## 2026-10-02 — 하이브리드 출연 방식 (REAL_UGC / AI_PRESENTER / AI_PRODUCT_UGC)
- `studio/presenter/`: modes(출연 방식·AUTO 우선순위·계획), real(실제 영상 구간 후보+배치), providers(VideoGenerationProvider 추상화·Router·미검증 stub·Mock), cost(ECONOMY/BALANCED/PREMIUM·월 예산 다운그레이드·생성 전 비용 표시), cache(동일 입력 재사용), fidelity(Product Fidelity QA: PASS/PRODUCT_MISMATCH/UNVERIFIED), generate(동의 후 생성·폴백·재생성 상한), safety(AI 진행자 가짜 사용 경험 금지)
- Storyboard: `StoryScene.source_type`, `StoryScene.ai`, `Storyboard.production` 추가 (기존 필드 변경 없음). DB: 마이그레이션 `0002_ai_generations`(기존 테이블/데이터 변경 없음)
- 파이프라인: 비용은 `generate_ai` 동의가 있을 때만(캐시 재사용은 무료), 실패/불일치는 원본 사진으로 대체, 최종 렌더 직전 미생성 AI 장면은 원본 확정
- API: form `actor_mode/cost_mode/monthly_budget`, `POST /jobs/{id}/ai-scenes`, 장면별 `edits.scenes.<id>.ai={action,prompt,provider}`; UI: 출연 방식/비용 모드, 장면 배지(ORIGINAL/REAL VIDEO/AI PRESENTER/AI UGC), 생성 전 비용 확인, 장면별 재생성/원본으로/프롬프트/Provider
- 전략: 사용 경험 표현(제가 써봤…)은 `my_take` 가 없으면 전 단계에서 금지, UGC_REVIEW 는 내부적으로 UGC_PRESENTATION/UGC_DEMO/UGC_REVIEW_VERIFIED 로 구분

## 2026-10-02 — 음악 폴더(BGM 라이브러리)
- `studio/bgm.py`: 폴더 분석(길이/음량/무음/BPM/적합도), 색인(`data/bgm_index.json`, 변경 없는 곡은 재분석 안 함), `choose`(상품 카테고리→폴더, 적합도 75+, 스타일 BPM 근접, 같은 상품은 같은 곡), `find_library`
- 파이프라인: 곡을 직접 지정하지 않으면 색인에서 자동 선택(없으면 내장 음악), 결과 `music` 에 이유 기록; `.gitignore` 에 음원 확장자 추가

## 2026-10-02 — 영상 스타일별 연출 차이
- `storyboard/styles.py`: STANDARD/FAST_COMMERCE/STORY_AD/UGC_REVIEW 프로필(장면 길이 배율·Hook 상한·음성 여유, 모션 선호 가감·카메라 세기, 전환, 효과음 비율/강한 효과음 허용, 음악 bpm/킥/패드/음량, 자막 속도)
- Motion Director `bias`, SFX Director `ratio/heavy`, `soft` 전환 렌더, 음악 베드 템포/킥 파라미터, EDL 에 style/intensity/music 전달
- 실측(Gemini 전략, 텀블러): FAST 6장면 13.6초 평균 2.3s·휩/플래시·124BPM / STORY 8장면 21.6초 평균 2.7s·소프트 전환·84BPM / UGC 6장면 17.2초 평균 2.9s·컷 위주·킥 없는 92BPM

## 2026-10-01 — SHOPPING_SHORTS_STRATEGY_ENGINE
### Added
- `studio/strategy/` (독립 모듈): selling.py(구매 이유 후보 6기준 평가→PRIMARY), angles.py(차별화 Angle 7기준→2개 선택), hooks.py(PROBLEM/CURIOSITY/EMPATHY x3→BEST_HOOK), script.py(HOOK→PROBLEM→SOLUTION→PROOF→CTA, 스타일별 구조), comment.py(OPINION_SPLIT/EXPERIENCE_SHARE/CURIOSITY), cta.py(SCARCITY/LOSS_AVERSION/SOCIAL_PROOF/DIRECT), audit.py(Funnel·8지표·이탈 타임라인·P0~P3·삭제 분석·Quality Gate), revise.py(자동 수정: 삭제/교체 우선), engine.py(단계 결과 저장·재사용·`pick`·기존 director 데이터로 변환), common.py(FACT SAFETY)
- 영상 스타일 3종 FAST_COMMERCE / STORY_AD / UGC_REVIEW (`ProductInput.video_style`, Storyboard.style)
- 파이프라인: STRATEGY 단계 → 기존 direct_scenes/Storyboard/Preview/Renderer 그대로 사용, Quality Gate 미통과 시 렌더 전 `STRATEGY_BLOCKED` (`strategy_force` 로 우회)
- API: `POST /api/v2/jobs/{id}/strategy`(재생성/선택/자동수정), `/storyboard`(Storyboard 만들기), render 는 게이트 미통과 시 409; UI: 전략 패널(단계별 [재생성], 후보 선택, 점검·자동 수정 내역), AUTO 최적화, 영상 스타일 선택; CLI: `--style --no-strategy --manual-strategy --force`
### Fixed
- 영상 클립 소스가 시연/사용 레이아웃이 아닌 레이아웃에 배정되면 렌더러가 mp4 를 이미지로 열어 실패 → 사진으로 되돌림
- LLM 점수 척도(1~5/0~1) 정규화, 사실 검증기 일시 오류 재시도, 게이트는 재현 가능한 규칙 점수만 사용

## 2026-10-01 — Preview Mode
### Added
- `studio/storyboard/preview.py`: 수정(edits) 반영 — 순서/삭제/나레이션/자막(대본), 레이아웃/모션/전환/이미지 교체/효과음 끔(스토리보드). 훅은 맨 앞·CTA는 맨 뒤 고정, 사용할 수 없는 레이아웃(시연 영상 없는 demo 등)·맞지 않는 모션은 이유와 함께 거부
- `ProductInput.preview/director_data/edits`, pipeline: preview 면 TTS·렌더 없이 장면 썸네일/선택지만 만들고 `PREVIEW_READY`, 확정 대본(director_data)은 렌더 때 AI 로 다시 쓰지 않음
- API: `preview=1` 폼 필드, `POST /api/v2/jobs/{id}/render {edits}`; studio.html 장면 카드 UI("미리보기 먼저" 기본 켜짐)
- 거부된 수정은 결과 화면에 "반영되지 않은 수정"으로 표시

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

- Added (품질 개선 V2, 2026-09-30): **PHOTO ENHANCEMENT V2** `studio/enhance.py` - 품질 분석 12항목(해상도/선명도/블러/잡음/노출/화이트밸런스/대비/빛번짐/반사(휴리스틱)/배경 복잡도/제품 가시성/압축 블록) → A/B/C 등급 → WB(±7%, 중립 픽셀 충분할 때만) → 노출·하이라이트·그림자(휘도 곡선, 채도 불변) → 잡음 → 선명화 → 저대비 → 보수적 업스케일(최대 1.5배, C 제외) → 배경 라우터(결정 기록) → **제품 충실도 QA**(같은 위치 픽셀 색상각/채도, 엣지 상관, 비율 + Gemini Vision 원본 대조; 실패 시 full → safe → 원본 순 폴백). ORIGINAL(`src/`) / ENHANCED(`enhanced/`) / DERIVED(`derived/`) 분리, 원본 덮어쓰기 없음. C 등급은 확대 컷 금지, 좋은 사진이 2장 이상이면 제외. `ProductInput.enhance`, CLI `--no-enhance`
- Modified: **FINAL QA V2** `qa.score_v2` - LOCAL TECHNICAL / VISION QUALITY / FINAL QUALITY 분리. 가중 평균 + 최약 핵심 항목 상한(+20) + Hard Gate(Visual<70→최대 74, AI Artifact<75→최대 79, Product Accuracy<85·Scene-Script<80→COMPLETE 금지, Visual·Commercial 모두 <70→QUALITY_FAIL). Vision 평가가 없으면 최대 79 + `NEEDS_REVIEW`(로컬 점수만으로 고품질 판정 안 함). FAST 도 Vision 1회 평가. 기준값은 `brain/system/quality_rules.yaml final_qa_v2`
- Added: **Commercial Feel**(조명/구도/제품 연출/배경 정리/카메라 느낌/화면 다양성/실제 광고 느낌/아마추어 느낌/AI 느낌 9항목, 최저값 반영), **Scene-Script Match**(프레임별 자막·대사 대조), **Source/Visual/Semantic Diversity**(같은 사진의 확대·크롭은 새 장면으로 30%만 인정), 개선 필요 목록(`qa.improvements`)
- Added: **12~15초 압축** `ProductInput.compact` / CLI `--compact` / 화면 체크박스 - 훅 1.2 → 공개 2.7 → 시연 3.6 → 혜택 3.3 → CTA 3.0, 역할당 1개 장면, 같은 사진 자동 분할 없음
- Modified(UI): 최종/기술/Vision 점수 병기, 개선 필요 목록(가장 큰 원인부터), 발동한 게이트 표시, `NEEDS_REVIEW` 표시, 상품 위험도 `UNKNOWN` → '카테고리 정보 부족 · 수동 확인 필요'

- Fixed: 사진 품질 분석의 흐림 판정 오류 (`enhance.focus_blur`) - 전체 평균 선명도(lapvar)는 매끈한 흰색 제품+보케 배경을 'C 심하게 흐림'으로 오판했다. 타일별 재블러 비율의 하위 20% (잡음 median 전처리)로 교체, 선명화 강도도 이 값으로 결정. 임시 보정치(표본 12종)
- Added(UI): 사진이 3장보다 적고 영상이 없으면 업로드 시점 안내 (실측 1장 61점 / 2장 67점)

- Added (STORYBOARD V2, 2026-10-01) — 기존 director/editor/renderer 는 유지하고 사이에 모듈 추가:
  - `studio/storyboard/`: `schema.py`(Storyboard/StoryScene JSON, 12/20/30/45초별 권장 장면 4~6/6~9/8~12/10~15), `engine.py`(대본 → Storyboard, 초과 시 우선순위 낮은 장면부터 제외·부족하면 억지로 늘리지 않고 경고), `scene_director.py`(장면별 narration/main·sub 자막/visual_source/transition/text_animation/music_cue/emphasis + 데이터 신뢰도 A/B/C), `sources.py`(Visual Source Router: 사용자 소스 우선, 부족 장면은 AI 영상 '후보'로만 기록·상한 2·provider 검증 전 호출 금지), `sfx_director.py`(전환/강조 지점에만, 연속 강타 금지, 장면 70% 상한), `layouts.py`(17종: 연속 반복 금지·계열 반복 벌점·비중앙 1/3 이상·후기/비교/전후는 사용자 실제 데이터가 있을 때만·시연은 실제 영상 클립이 있을 때만), `motion_director.py`(15종: 대사/목적/특징어/레이아웃 호환 기반, 랜덤 없음, 이유를 decisions 에 기록, 연속 동일 금지·줌 계열 60% 상한), `validator.py`(영상 퀄리티 규칙 11가지 검사 + 안전한 자동 수정)
  - Renderer: `studio/layout_render.py`(17종 그리기, 배경/제품 분리 합성, 개인정보 타이트 크롭 존중), `studio/camera.py`(모션 15종 수식), `studio/storyboard_edit.py`(Storyboard → EDL: 장면 1개 = 컷 1개, 효과음 이벤트, 음성 길이 맞춤), `Shot.layout/motion/source2/data/emph_at`, `MotionRenderer.cam_for`
  - 기본 렌더 경로가 Storyboard 로 전환 (기존 경로는 `ProductInput.legacy_render` / CLI `--legacy-render`), `ProductInput.review_quotes/before_after/comparison`
  - 효과음 합성 5종 추가(click, ding, impact, swipe, soft_hit) + transition_hit → 총 9종
  - QA: layout 을 구분해 연속 동일 구도 판정, 영상 클립 소스 키, Storyboard 경로 평균 컷 길이 기준 `storyboard_avg_shot_length [1.4,3.2]` (장면마다 레이아웃/모션이 달라 컷이 조금 길어도 단조롭지 않다는 근거. 기존 경로 기준은 그대로)
- Fixed: 규칙 대본의 크기 주장 템플릿 '이게 생각보다 커요' 제거, 매크로 컷이 큰/원형 제품을 자르던 문제(레터박스, 타이트 크롭 기준 보정)

### Known Issues
- 외부 AI(LLM/TTS/영상 생성) 실호출 미검증 — 키 없음 + 샌드박스 네트워크 차단
- 사람/손이 나오는 실제 사용 장면은 영상 생성 provider 연결 전까지 만들 수 없음 (현재는 원본 사진 모션)
- 로컬 Final QA 는 측정 지표 기반이라 "장면-자막 의미 일치", "고급스러움" 같은 사람 판단은 못 함 → Vision LLM 연결 필요
- 테스트 상품이 합성 이미지 (실사진 1장만 사용)
