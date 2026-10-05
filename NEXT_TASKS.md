# NEXT_TASKS

## 1. 실제 상품 사진 재테스트 (진행 중: 3개 완료 — 독서대, 물티슈, 차량 거치대, 2026-09-30)
- 완료: 독서대(생활), 물티슈(유아, 저해상도 2장), 차량 거치대(전자기기, 통과). 남은 것: 주방/전자기기/뷰티/운동. 단색 배경 사진과 사용 장면 사진이 있는 상품이 특히 필요
- NEXT TASK: 생활/주방/전자기기/뷰티/운동 실제 상품 사진(정면·옆·디테일·사용 장면, 긴 변 1500px 이상)으로 FAST/PRO/PHOTO ONLY 실행
- FILES TO OPEN: `TEST_RESULTS.md`, `shortsmaker/studio/pipeline.py`, `shortsmaker/studio/qa.py`
- CURRENT PROBLEM: 샌드박스에서 실제 상품 사진을 받을 수 없어 합성 제품 이미지로만 검증됨
- EXPECTED RESULT: 영상별 점수·문제를 TEST_RESULTS.md 에 기록, cutout/매크로 초점/자막 위치 튜닝
- DO NOT REDO: 파이프라인/QA/Compliance 구조
- AFTER THIS: 2번

## 1-B. 쿠팡 이미지 권리 (사용자 확인 필요)
- 사용자 사진은 쿠팡 상품 이미지. 게시 전 쿠팡 파트너스 약관(이미지 사용 조건) 확인 또는 판매자 허락/직접 촬영 사진 필요
- 나중에: Coupang Partners API 로 상품 정보/이미지를 가져오는 정식 경로 연동 검토 (Seller API / Partners / 페이지 import 를 혼동하지 말 것)

## 0000000000000. 상품 없는 일상 다음 단계 (2026-10-05)
- 실제 일상 사진·영상으로 PC 에서 시험, 영상 길이/구간 직접 지정, 사진 순서 바꾸기(UI), 장면별 메모를 사진 옆에 입력, 가로 영상 처리 개선(지금은 흐린 배경 위 가운데 배치), 일상 전용 품질 점검(판매 점수 대신 가독성/템포/자막 위치 등), 주제만 입력해 무료 B-roll 로 구성(Pexels/Pixabay 연결 필요)
- 순서 규칙: 사진 먼저, 영상은 그 다음 장면 — 사진/영상을 섞은 순서는 아직 지정할 수 없음

## 000000000000. 일상 속 상품 다음 단계 (2026-10-05)
- 실제 일상 사진·영상(2~4장 + 짧은 영상)으로 PC 에서 시험 필요 — 합성 사진으로는 '일상 느낌' 자체를 판단할 수 없음
- 아직 안 한 것: 순수 일상(상품 없는) 브이로그형, 주제만 입력해 무료 B-roll(Pexels/Pixabay 연결 필요)로 구성, 일상 유형 전용 품질 점검(Hook/CTA 점수 기준이 판매용이라 일상에는 맞지 않을 수 있음), 일상 메모를 장면별 사진에 직접 연결
- 일상 유형도 최종 QA 점수는 상품 쇼츠 기준으로 계산됨(Hook/Story/CTA) — 점수 해석 주의

## 00000000000. 모션그래픽 다음 단계 (2026-10-04)
- 웹 UI 에서 생성(사진 업로드→모션그래픽 MP4), 기존 쇼츠 파이프라인의 장면 전환/타이포로 이식, 장면 길이/BPM/색상 선택, 1080x1920 출력(현재 540x960: 속도 때문에 낮춤)
- 사람이 폰으로 보고 확인할 것: 펀치/전환 강도, 글자 크기, 효과음 볼륨. 한계: 데모는 합성 텀블러 사진, 한글 폰트 외 언어 미검증

## 0000000000. 하이라이트 선택 다음 단계 (2026-10-03)
- 실제 사용 영상(3분 내외)으로 사람이 확인: 고른 구간이 정말 쓸 만한지, 신호 가중치(동작 0.3/소리 0.12/제품 0.3/사용 0.25) 조정
- 아직 안 한 것: 말소리(대사) 기반 구간 선택(STT 필요), 컷 경계(장면 전환) 스냅, 후보 구간 썸네일 미리보기, 사용자가 후보에서 직접 고르기

## 000000000. 다국어 지원 (보류 — 나중에 작업, 2026-10-03)
- 현재는 한국어 전용: 전략 엔진 문장 규칙/조사/줄바꿈, 자막 폰트(한글 중심), TTS 언어 지정 없음, 플랫폼 문구·규정 점검이 한국 기준. 영상 프롬프트(UGC/3-Scene Flow)와 렌더/편집/SNS 마감은 언어 무관
- 접근(작업량 순): ① 번역 출력(한국어 대본·자막 → 목표 언어 + 번역본에도 사실 검증 재적용, 언어별 폰트/TTS 음성 선택) ② 언어별 문체·금지 표현 규칙(사실 안전 기준은 공통 재사용) ③ 플랫폼 현지화(해시태그/규정/통화/판매처 문구)
- 시작 전 정할 것: 대상 언어(영어/일본어 등), 한국어 영상 경로는 그대로 두고 선택 기능(기본 OFF)으로 추가. 한계: 번역 자연스러움은 현지인 확인 필요

## 00000000. OpusClip 방식 편집 다음 단계 (2026-10-03)
- 아직 안 한 것(효과 큰 순): ① 긴 영상에서 하이라이트 구간 자동 선택(ClipGenius 류, 기존 clips.py 구간 선택 확장) ② 자막 스타일 프리셋(활성 단어 하이라이트/이모지, 사람이 보고 고르기) ③ 말 사이 무음 제거(TTS 앞뒤 여백 정밀 트리밍) ④ B-roll 자동 삽입 ⑤ 플랫폼 UI 가림 점검(플랫폼별 하단/우측 영역)
- 확인 필요: 폰에서 실제로 보았을 때 펀치 줌이 과한지(+0.07 배율, 컷당 최대 2회) — 사람이 봐야 함
- Provider 교체 구조는 이미 있음(영상 생성 VideoGenerationProvider, LLM/비전/TTS Router). Runway/Higgsfield/Flow 어댑터는 실제 호출 검증 전까지 미연결

## 0000000. 3-Scene Flow Mode 다음 단계 (2026-10-03)
- 실제 Google Flow 에 샘플 Scene 1~3 을 넣어 결과(손/제품 일관성)를 사람이 확인해야 함 (Flow 는 자동 호출하지 않음 — 공식 API 연결 미검증)
- Scene 간 시작/끝 프레임 이어 붙이기(Flow 의 frames-to-video) 활용 여부, 장면별 프롬프트 편집/저장, Scene 4~5 확장은 2차

## 000000. UGC Reference Mode 다음 단계 (2026-10-03)
- 2차 후보: URL 자동 수집(Instagram/샤오홍슈/TikTok), 고급 영상 분석(프레임 단위), 자동 렌더/게시(승인 후), 분석 재사용 라이브러리 UI, 장면별 영상 프롬프트 provider별 변환
- 실제 Gemini 로 실제 UGC 영상 3~5개를 분석해 본 적 없음(합성 fixture 로만 검증). 실제 AI 영상 provider 호출은 여전히 미검증

## 00000. REFERENCE_VIDEO_ENGINE 다음 단계 (2026-10-02)
- 구현됨: 분석기(YouTube URL=Gemini / 업로드 영상=로컬+Vision / 구조 메모), 패턴 추출(어휘 값만), Pattern Library(DB 0003), Pattern Mix(AUTO/수동), 상품 적응(근거 없는 상황 단계는 제외), 템포/전환/모션/CTA/Hook 유형 적용, 복제 방지(해시) + 번역투 금지, Licensed Remix 권한 검문(구조), Reference Lab UI/API
- **실제 플랫폼 영상 분석은 YouTube 일반 영상 1개(뮤직비디오)로만 확인.** Reels/샤오홍슈 실제 영상, 쇼핑 쇼츠 분석 품질, 10개 Reference 실측은 미검증 (환경에서 접속 불가). 사용자 PC에서 실제 URL/영상으로 시험 필요
- NEXT 1: 사용자 PC 에서 실제 쇼츠/릴스/샤오홍슈 영상 10개 분석 → 패턴 품질(Vision/Gemini 응답 정확도) 확인, 어휘 보정
- NEXT 2: Instagram/샤오홍슈 URL 은 영상 접근 불가(다운로드 제외) → 업로드/메모 방식만. 공식 API/oEmbed 로 가능한지 검토
- NEXT 3: 패턴의 늦은 공개(예: 9.5초)와 빠른 편집 템포(Reels)를 섞으면 공개 시점이 앞당겨짐(템포 우선). 우선순위 규칙 필요
- NEXT 4: 복제 방지는 Gemini 가 말/자막 원문을 돌려줄 때만 해시 생성(음악 영상 등은 0개). 원문이 없으면 검사 불가
- NEXT 5: Licensed Remix 는 권한 표시와 허용 연산 검문까지만 (실제 재편집 UI/렌더 연결 없음)
- NEXT 6: 패턴 적용 전/후의 '실제 시청 품질' 비교(사람 평가). 지금 비교는 구조 지표(템포/공개/레이아웃 다양성/전략 점수) 위주
- DO NOT REDO: reference_engine 패키지 (analyzer/patterns/library/mix/apply/remix/fingerprint/vocab)

## 0000. 하이브리드 출연 방식 다음 단계 (2026-10-02)
- 구조 구현됨 / 실제 외부 API 호출은 **0건** (Higgsfield/Seedance/Kling 은 자리만, 공식 문서 검증 전 호출 금지)
- NEXT 1: provider 하나를 공식 문서로 검증(엔드포인트·가격·이미지→영상 파라미터)해서 `presenter/providers.py` 에 어댑터 추가 → 그 전에는 AI 장면이 항상 원본 사진으로 대체됨
- NEXT 2: AI Presenter 립싱크(대사 음성과 입 모양) 미구현 — 지금은 영상만 만들고 음성은 TTS 로 덮음
- NEXT 3: Product Fidelity 는 Vision 비교(LLM)에 의존. 로컬 외형 비교(색/엣지) 없음, Vision 이 없으면 UNVERIFIED → AI 장면 미사용
- NEXT 4: Preview→[AI 장면 생성]은 새 작업으로 처음부터 다시 실행(사진 분석/전략 재사용 안 함). 상태 저장/재사용 필요
- NEXT 5: 월 예산은 가격을 아는 provider 가 생겨야 의미 있게 동작(지금은 기록된 지출만 비교). 실제 가격 조회 API 없음
- NEXT 6: 실제 사용 영상의 행동 태그(손에 들기/사용/버튼)는 Vision 있을 때만, 얼굴 노출 구간 제외 규칙은 없음(기존 개인정보 검사만)
- DO NOT REDO: presenter 패키지(modes/providers/cost/cache/fidelity/generate/real/safety)

## 000. SHOPPING_SHORTS_STRATEGY_ENGINE 다음 단계 (2026-10-01)
- 완료: 7단계 전략 엔진(`studio/strategy/`) + Quality Gate + 자동 수정 + 영상 스타일 3종(FAST_COMMERCE/STORY_AD/UGC_REVIEW, 구조·Hook·CTA 가 다름) + 파이프라인/Preview/UI/CLI 연결
- 남은 문제 (TEST_RESULTS.md 참고)
  1. Preview 에서 대본/자막을 직접 고치면 전략의 Conversion Audit 점수는 다시 계산되지 않음 (edits 이후 재점검 필요)
  2. (해결) 스타일별 컷 템포/모션 선호/카메라 세기/전환/효과음/음악/자막 속도 차이 구현(`storyboard/styles.py`). 남은 것: 스타일별 레이아웃 선호, PREMIUM 스타일, 실제 사람이 보고 '다르게 느끼는지' 확인(측정은 설정값 차이까지)
  3. Hook 9개(유형별 3개)를 항상 채우지는 못함: 사실 검증기가 엄격해 입력 정보가 적은 상품(문제 미입력)은 3~7개만 남음
  4. 전략 한 번에 100~160초 (LLM 호출 약 10회 + 사실 검증). 병렬화/캐시 필요
  5. 사실 검증기(LLM)는 '풀어쓴 효과'("바로 풀어보세요")를 일부 통과시킴. 판매 주장 장면은 입력 사실과의 겹침(A)을 요구하지만 Hook/CTA 는 B 허용
  6. Proof 는 후기/직접 써본 느낌/영상이 없으면 '실제 모습' 수준 → trust_proof 상한 70
  7. 카테고리 '흔한 패턴'은 일반 경향(B)이며 외부 영상 실측이 아님 (경쟁 영상 수집 기능 없음)
  8. 중간 Soft CTA 는 미구현(기록만), 댓글 장치는 별도 짧은 장면으로 삽입(FAST/12~15초는 삽입 안 함)
  9. 쿠팡 상품 URL 은 이 개발 환경에서 접속 불가(403) → 실제 쿠팡 페이지 대상 테스트는 사용자 PC 에서만 가능
- DO NOT REDO: strategy 패키지(selling/angles/hooks/script/comment/cta/audit/revise/engine)

## 00. STORYBOARD V2 다음 단계 (지시서 순서)
- 완료: Storyboard Engine, Scene Director, Layout Engine, Motion Director, Storyboard→Renderer 연결, 영상 퀄리티 규칙 검증기, 효과음 9종, 신뢰도 A/B/C
- 완료: **Preview Mode** (`storyboard/preview.py`, `POST /api/v2/jobs`(preview=1) → PREVIEW_READY → `POST /api/v2/jobs/{id}/render`). 남은 것: 장면 단위 '재생성'(AI 문구 다시 쓰기)과 레이아웃 변경 시 모션 선택지 즉시 갱신(UI), 미리보기 → 렌더 때 분석 단계 재실행 비용 줄이기(캐시)
- NEXT TASK 2: **Video Style Variation** — FAST_COMMERCE / PREMIUM / UGC_REVIEW 연출안 3종 (`Storyboard.style`, `MUSIC_BY_STYLE` 자리만 있음)
- NEXT TASK 3: Visual Source Router 나머지 단계(상품 URL/상세페이지 이미지, 무료 B-roll(Pexels/Pixabay 키 있음·미연결), AI 이미지/영상 — provider 검증 후 부족 장면에만)
- NEXT TASK 4: `text_animation` 렌더 지원 (현재 word_pop 만 렌더, scale_pop/fade_in/slide_up 은 기록만)
- 사용자 조치: 소스(사진 3~4장 이상, 사용 장면 영상)가 점수를 결정함 (TEST_RESULTS.md)
- 주의: 지시서의 'Remotion + FFmpeg' 는 이 저장소에 없고 렌더러는 Python(Pillow/numpy) → FFmpeg 파이프. Renderer 는 Storyboard JSON 으로만 입력받도록 분리됨
- DO NOT REDO: storyboard 패키지, layout_render, camera, storyboard_edit, validator

## 0. 품질 개선 다음 단계 (V2 검증 결과 반영, 2026-09-30) — 최우선
- 현재 문제: 사진 2장만으로는 Visual 52~55 / Commercial 47 (Gemini). 보정·크롭으로는 더 오르지 않음 (TEST_RESULTS.md)
- NEXT TASK 1: **PRIORITY 6 Source Library + Semantic Clip Matcher** — 입력 사진/영상을 라이브러리로 저장, 영상은 장면 분할 + Gemini 로 metadata(action/usage/product_visibility/시간 구간), 대사·자막 의미와 맞는 클립 자동 배치, 불일치는 Final QA FAIL. (기존 `studio/clips.py` 의 구간 선택/재생/개인정보 검사를 재사용)
- NEXT TASK 2: 실제 사용 장면 영상(손으로 설치/사용, 3~10초)을 받아 D. SOURCE VIDEO 실험 (실제 폰 영상 필요)
- NEXT TASK 3: PRIORITY 7 AI 영상은 Source Library 에 없는 장면에만 (Seedance/Higgsfield/Veo 중 공식 API 문서로 검증 가능한 하나). 추측 endpoint 금지
- 사용자 조치(코드로 못 고침): 단색/정리된 배경 + 자연광 촬영, 정면/옆/디테일/사용 장면 각 1장 이상, 제품이 화면의 60~80%
- FILES TO OPEN: `shortsmaker/studio/clips.py`, `shortsmaker/studio/qa.py`(score_v2), `shortsmaker/studio/enhance.py`
- DO NOT REDO: enhance.py 분석/보정/충실도, qa.score_v2 점수 체계, 12~15초 압축, 배경 정리(spotlight)
- 미검증: Vision 충실도 비교 실호출(보정본이 생성된 실사진 필요), 사람 손이 나오는 클립에서의 구간 선택

## 2-V. 영상 클립 다음 단계 (1단계 완료: 업로드 + 구간 자동 선택 + 컷 삽입)
- 실제 폰으로 찍은 사용 장면 클립으로 재테스트 (손/조명/흔들림이 있는 실제 영상). 합성 클립으로만 검증됨
- 2단계 후보: Gemini 영상 이해로 '사용 장면인지/제품이 보이는지' 판정해 컷 배정 정교화, 클립 안 얼굴/번호판 블러 처리(현재는 클립 통째 제외), 클립 슬로모/속도 조절, 컷당 클립 1개 → 한 컷에 여러 구간, 클립 전용 품질 점수
- DO NOT REDO: `studio/clips.py` 분석/배정/재생, `video_clip` 샷

## 2-M. 모바일/앱 다음 단계
- 사용자: 서버를 실제로 띄워 폰(HTTPS)에서 설치·촬영·공유 확인 (MOBILE.md). 결과는 알려주면 수정
- 나중에: Web Share Target(갤러리에서 바로 공유해 보내기), 푸시 알림(제작 완료), Capacitor 로 스토어 앱 포장(Android SDK/Apple 개발자 계정 필요), 작업 큐 영속화(재시작 시 진행 중 작업 복구)
- DO NOT REDO: auth.py, PWA 자산, studio.html 모바일 레이아웃

## 2-0. Gemini 연결 완료 (2026-09-30) — 다음 단계
- 완료: Vision 자동 박스/특징 연결/개인정보 감지, AI 대본 + 근거 검증, 플랫폼 문구 검증, Vision 최종 평가
- NEXT: (a) TTS(ElevenLabs/OpenAI 키) (b) 더 좋은 조명의 사진으로 재테스트 — Vision 평가를 통과하는 영상이 나오는지 (c) 웹 화면에 grounding 결과·경고(개인정보) 표시 (d) 실제 청구 단가로 레지스트리 비용 보정
- DO NOT REDO: grounding, vision.py, 자격 증명 자동 감지

## 2. LLM provider 연결 (OpenAI 또는 Gemini)
- NEXT TASK: `.env` 에 키 입력 → `/control` Test All → `model_registry.yaml` 모델 ID 를 실제 목록과 대조해 수정, `last_verified` 기입
- FILES TO OPEN: `shortsmaker/providers/model_registry.yaml`, `shortsmaker/providers/llm.py`, `shortsmaker/studio/director.py` (`llm_director`)
- CURRENT PROBLEM: 대본은 규칙 기반이라 문장이 정형적. Vision QA 없음
- EXPECTED RESULT: LLM 기획(JSON) → 같은 후처리/검증 통과, Final QA 에 vision_llm 점수 추가
- DO NOT REDO: Router/폴백/비용 기록
- AFTER THIS: 3번

## 3. TTS 연결 (ElevenLabs 또는 OpenAI TTS)
- NEXT TASK: 키 입력 후 PRO 1개 생성, 장면 길이가 음성 길이에 맞는지(Dead air) 확인
- FILES TO OPEN: `shortsmaker/studio/tts.py`, `shortsmaker/studio/editor.py`, `shortsmaker/studio/audio.py`
- CURRENT PROBLEM: 보이스오버 없음 (Audio 점수 80)
- EXPECTED RESULT: 보이스 + 음악 덕킹, 자막 단어 타이밍이 음성과 맞음
- DO NOT REDO: 믹서/덕킹
- AFTER THIS: 4번

## 4. 영상 생성 provider adapter (Seedance 우선, first/end frame)
- NEXT TASK: 공식 API 문서로 요청/응답/폴링 형식 확인 → `media.py` 의 `SeedanceProvider.generate` 구현 → registry `enabled: true`
- FILES TO OPEN: `shortsmaker/providers/media.py`, `shortsmaker/studio/pipeline.py` (`video_route`, VIDEO_GEN 단계), `shortsmaker/studio/qa.py`
- CURRENT PROBLEM: 사람/손 사용 장면을 만들 수 없음 (현재 원본 사진 모션)
- EXPECTED RESULT: demo/benefit 장면만 Draft(저비용) → Visual QA → Premium, 제품 변형 심하면 image motion 폴백
- DO NOT REDO: 라우팅 규칙, take 선택 구조
- AFTER THIS: 5번

## 5. B-roll (Pexels → Pixabay) + 문제 장면 강화
- NEXT TASK: problem 비트에 스톡 영상(STOCK_LICENSED) 사용, 자산 권리 DB 기록
- FILES TO OPEN: `shortsmaker/providers/media.py`, `shortsmaker/studio/motion.py`, `shortsmaker/studio/editor.py`
- CURRENT PROBLEM: 문제 장면이 흐린 제품 이미지로 대체됨
- EXPECTED RESULT: 문제 → 해결 대비가 영상으로 보임
- DO NOT REDO: rights gate
- AFTER THIS: Performance 입력 화면, Supabase 이전 검토

## 참고: GitHub push
- Claude GitHub App 에 `dkrkwnsdyd-lang/-` 쓰기 권한이 없어 push 403. 권한 해결 후 `git push -u origin claude/youtube-shorts-auto-generate-sn7b76`

---

## NEXT SESSION PROMPT

```
SHOP SHORTS AI V2 개발을 계속 진행하라.

먼저 읽어라:

PROJECT_STATUS.md
NEXT_TASKS.md
API_STATUS.md
CHANGELOG_V2.md
TEST_RESULTS.md

완료된 기능을 다시 만들지 마라.

현재 코드와 상태 파일이 일치하는지 짧게 확인하고,
NEXT_TASKS.md 첫 번째 미완료 작업부터 즉시 진행하라.

기존 DB와 정상 기능을 보호하라.

현재 최우선 목표:
실제 상품 사진 5개로 FAST / PRO / PHOTO ONLY 재테스트 후, 연결된 API 키가 있으면 LLM → TTS → 영상 생성 provider 순서로 실제 연결·검증

작업 종료 전 모든 상태 파일을 업데이트하라.
```
