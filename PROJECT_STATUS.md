# PROJECT_STATUS — SHOP SHORTS AI V2

## Current Phase
V2 1차 완료: Audit → API V2 → Scene Director V2 → Product Lock → Storyboard/Visual QA → First/End Frame(서술) →
Multi Take → Best Take → AI Editor → Final QA → PRO 영상 → Photo Only → Multi Platform → Compliance

## PROJECT AUDIT (2026-09-28)
지시서가 가정한 기존 구성(Supabase, Remotion, Next/React, Naver Import, Review Miner, Hook/Script Generator,
TTS, Job Queue 등)은 **이 저장소와 접근 가능한 다른 저장소(`dkrkwnsdyd-lang/1`, blog-image*) 어디에도 없었다.**
실제로 있던 코드는 V1 `shortsmaker` (사진 슬라이드 영상 + 4개 플랫폼 업로드) 뿐이어서 V2 는 그 위에 확장했다.

1. 정상 동작 기능 (V1): 사진→슬라이드 mp4(`video.py`), 입력 처리(`sources.py`), 업로드 4종(`platforms/`), 웹/CLI
2. 중복 기능: 없음 (V2 는 `video.ffmpeg_exe`, `platforms/*` 업로더를 재사용)
3. 깨진 기능: 없음. 단, 유튜브 썸네일 입력은 샌드박스에서 i.ytimg.com 차단으로 실테스트 불가
4. 오래된 API/모델: 없음 (모델 하드코딩 없음 → V2 에서 registry 로 관리)
5. **영상이 허접해지는 핵심 원인 (V1)**: 모든 사진이 같은 켄번스+크로스페이드, 스토리/훅 없음, 컷 리듬 없음,
   자막이 정적, 음악/효과음 없음, 제품 배경 처리 없음, 품질 검사 없음
6. 개선 우선순위: 지시서 58번 순서 그대로 진행
7. API 연결 상태: 전부 미연결 (API_STATUS.md)

## Completed
- SHORTS BRAIN 3영역 분리 (SYSTEM / LEARNED / JOB)
- Provider 추상화 + MODEL REGISTRY + Router(재시도·폴백·비용·키 마스킹) + API Control Center(`/control`)
- SQLite + up/down 마이그레이션, JOB QUEUE 단계 기록, COST TRACKING, QA 기록, 자산 권리 기록
- Product Intelligence(사진 분석, URL 공개 메타데이터), PRODUCT LOCK(Identity), Photo Only 모드
- Selling Angle / Story Director(10패턴) / Hook 3후보 / Script / Scene Director V2(20필드) / 길이 자동 결정
- Storyboard Visual QA + 장면 재시도(MAX 2), VIDEO ROUTER(검증된 provider 없으면 image motion)
- Multi Take(Hook 3, Demo 2) + Best Take Selector(점수·선택 이유 기록)
- AI Editor(첫 3초 규칙, 컷 분할, 박자 컷, 펀치 줌, SFX), 다이내믹 자막(단어 팝, 강조색, 2줄, 안전영역)
- High Quality Image Motion 렌더러 (샷 10종) + 자체 음악/효과음
- Final Video QA(측정 기반 11항목) + 수리 루프(MAX_FINAL_RETRY 2) — COMPLETE 는 품질 통과일 때만
- Multi Platform Adapter(플랫폼별 CTA 장면·문구·LUFS·인코딩), Compliance Gate(상품/주장/건강/고지/권리)
- Reference Miner(로컬 mp4 구조 분석, YouTube URL 은 Gemini 연결 시)
- 웹 스튜디오 `/` (URL/사진, FAST/PRO, 참고영상, 플랫폼 체크, 품질·안전 결과), CLI `studio`

## In Progress
- 없음 (세션 종료 전 안정화 완료)

## Not Started
- 실제 AI 영상 생성 adapter (Seedance/Higgsfield/Veo) — 공식 문서 확인 + 키 필요
- 캐릭터 락(사람 등장 장면이 생길 때), 부족한 각도 자동 생성(이미지 생성 provider 필요)
- B-roll(Pexels/Pixabay) 파이프라인 연결
- Review Miner (리뷰 데이터 소스 없음), Shorts Suitability Score
- Performance Loop 입력 화면 (테이블만 있음)
- Supabase 이전 (현재 SQLite, SQL 호환 작성)
- Remotion (현재 FFmpeg 파이프 렌더러로 충분)

## Blocked
- GitHub push: Claude GitHub App 쓰기 권한 403 (코드는 로컬 커밋 + 번들 파일로 전달)
- 외부 API 실테스트: 키 없음 + 샌드박스 네트워크 정책

## Known Bugs
- 합성 테스트 이미지의 바닥 그림자가 제품과 함께 잘려 나와 떠 있는 원반처럼 보일 수 있음(실사진에서 재확인 필요)
- 로컬 QA 는 장면-자막 의미 일치(예: "USB-C 충전" 자막인데 포트가 안 보임)를 판단하지 못함
- 문제(problem) 장면은 실제 불편 상황 영상이 없어 흐린 제품 + 자막으로 대체

## Working Features
V1 전체 + V2 파이프라인 (`python -m shortsmaker studio 사진.jpg --name … --category 주방`), 웹 `/`, `/control`

## Broken Features
- 없음

## Database State
`data/shorts.db` (SQLite) — migration `0001_v2_init` 적용. rollback: `python -m shortsmaker db-rollback`

## API State
전부 미연결. 로컬 provider(rule_director_v1, image_motion_v2, pixel_stats_v1)로 동작.

## Video Pipeline
입력 → 사진 분석/Identity → (참고영상) → 기획(LLM|규칙) → Scene V2 → Storyboard QA(+재시도) → Router →
Multi/Best Take → (TTS) → AI Editor → 렌더(body + CTA) → 믹스 → MASTER → Final QA(+수리) →
플랫폼 문구 → Compliance → 플랫폼별 CTA 렌더 + concat + LUFS export

## Last Successful Test
2026-09-28 — pytest 45 passed, 실영상 배치 16개 (13 COMPLETE / 3 QUALITY_FAIL: FAST 2개 단조로움, 저해상도 실사진 1개) — TEST_RESULTS.md

## Important Decisions
- 기존 코드 재작성 없이 확장 (V1 화면은 `/classic` 로 유지)
- 영상 생성 API 는 공식 문서 검증 전까지 호출하지 않음 → 추측 endpoint 로 유료 호출 방지
- 생성 영상 대신 **원본 사진 모션**을 기본값으로: 제품 변형 0 (Product Lock > 화려함)
- 음악/효과음은 코드로 합성 (저작권 리스크 0)
- UNKNOWN 카테고리는 자동 GREEN 금지 → 플랫폼 판정 UNKNOWN, export 보류
- Compliance 판정이 PASS/PASS_WITH_WARNING 인 플랫폼만 export
