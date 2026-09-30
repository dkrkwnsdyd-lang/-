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
