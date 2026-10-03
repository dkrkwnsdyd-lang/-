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

## 2026-10-03 UGC Reference Mode 1차 구현됨 (기본 OFF, 합성 fixture 검증, 실제 영상·AI 호출 미검증)

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

## 실사진 첫 테스트 (2026-09-29)
투명 아크릴 독서대 사진 2장으로 FAST/PRO/PHOTO ONLY 실행. 점수가 품질을 과대평가한 문제를 발견해 수정. TEST_RESULTS.md 참고.

## 실사진 두 번째 테스트 (2026-09-29)
베이비 물티슈 2장(저해상도)으로 PRO/FAST/PHOTO ONLY. 코드 문제 7건 수정, 남은 실패 원인은 원본 해상도/사진 수. TEST_RESULTS.md 참고.

## 실사진 세 번째 테스트 (2026-09-30)
직접 촬영한 차량 거치대 사진 2장 → **PRO/FAST 처음으로 품질 통과(98점)**, 플랫폼 4곳 🟢. 자막-화면 불일치 발견해 특징-사진 연결 추가.

## 사용자 확인 (2026-09-30)
M-Circle 상품명/특징(컬러 LED 링, 송풍구 클립 거치)과 쿠팡 파트너스 제휴 여부를 사용자가 확인함. 게시용 4개 파일+문구 전달.

## Gemini 연결 (2026-09-30)
환경 자격 증명으로 연결·호출 성공. Vision 자동 채움/AI 대본/근거 검증/Vision 최종 평가까지 실호출 검증. 영상 1개 약 $0.014(추정 단가). AI 대본이 입력에 없는 주장을 지어내는 문제를 발견해 grounding 으로 차단. 남은 감점은 원본 사진 품질.

## 모바일/앱 (2026-09-30)
PWA(홈 화면 설치) + 모바일 화면 + 접근 암호 + Docker 배포 파일 완료. 스토어 앱(APK/iOS)은 미제작. 실제 폰/HTTPS 배포는 미검증(에뮬레이션과 깨끗한 가상환경 설치로만 검증). MOBILE.md 참고.

## 영상 클립 (2026-09-30)
직접 찍은 상품 영상 클립을 사용 장면 컷에 삽입(1단계). 합성 클립 + 실제 Gemini 개인정보 검사로 끝까지 검증, 실제 폰 영상은 미검증. CHANGELOG_V2.md 참고.

## 품질 개선 V2 (2026-09-30)
PHOTO ENHANCEMENT V2(등급/보정/충실도 QA), FINAL QA V2(로컬 기술/Vision/최종 점수 분리 + Hard Gate + Commercial Feel + Scene-Script + 다양성), 12~15초 압축, 화면 개선, 참고 URL(검색결과 UNVERIFIED) 완료.
**실사진(M-Circle 2장) 검증 결과 Final 66~68 QUALITY_FAIL — 성공 기준 미달.** 원인은 화질이 아니라 소스(어수선한 배경, 스냅 조명, 사진 2장 재사용, 사용 장면 없음). TEST_RESULTS.md 참고.

## STORYBOARD V2 (2026-10-01)
Script → Storyboard Engine → Scene Director → Layout Engine → Motion Director → (검증/자동수정) → Storyboard→EDL → Renderer 구조 완료(기본 경로). 17 레이아웃·15 모션·효과음 9종.
**실사진(M-Circle 2장) 점수는 기존 경로와 구분되지 않음(71 vs 72/67, 모두 QUALITY_FAIL).** 레이아웃/모션은 표현을 다양화하지만 소스 부족(사진 2장 반복)은 해결하지 못함. 아직 없음: Preview 편집 UI, 연출안 3종(FAST_COMMERCE/PREMIUM/UGC_REVIEW), 무료 B-roll/상세페이지 소스, text_animation 일부(scale_pop/fade_in/slide_up)의 렌더 지원.

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
2026-09-28 — pytest 74 passed, 실영상 배치 16개 (13 COMPLETE / 3 QUALITY_FAIL: FAST 2개 단조로움, 저해상도 실사진 1개) — TEST_RESULTS.md

## Important Decisions
- 기존 코드 재작성 없이 확장 (V1 화면은 `/classic` 로 유지)
- 영상 생성 API 는 공식 문서 검증 전까지 호출하지 않음 → 추측 endpoint 로 유료 호출 방지
- 생성 영상 대신 **원본 사진 모션**을 기본값으로: 제품 변형 0 (Product Lock > 화려함)
- 음악/효과음은 코드로 합성 (저작권 리스크 0)
- UNKNOWN 카테고리는 자동 GREEN 금지 → 플랫폼 판정 UNKNOWN, export 보류
- Compliance 판정이 PASS/PASS_WITH_WARNING 인 플랫폼만 export


## SHOPPING_SHORTS_STRATEGY_ENGINE (2026-10-01)
상품 분석 → 구매 이유 → 차별화 Angle → Hook → 판매 대본 → 댓글 장치 → CTA → Conversion Audit(+자동 수정, Quality Gate) → Storyboard → Preview → MP4. 기존 Renderer/Storyboard/Preview 그대로 연결, 기존 director 는 `--no-strategy` 로 유지. 한계는 NEXT_TASKS.md 000 항목, 실측 결과는 TEST_RESULTS.md 참고.
