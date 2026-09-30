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
