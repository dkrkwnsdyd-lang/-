# Codex / 자동 코딩 에이전트 지침 — SHOP SHORTS AI

모든 변경 전에 `docs/AI_TEAM_WORKFLOW.md`와 `PROJECT_STATUS.md`, `NEXT_TASKS.md`, `TEST_RESULTS.md`를 읽을 것.

## 작업 기본 규칙
1. 현재 저장소는 Python + FastAPI + PWA + FFmpeg 기반이다. 별도 승인 없이 Next.js/Remotion 등으로 재작성하지 말 것.
2. 기존 `shortsmaker/`, `tests/`, `/classic`, `/control` 기능을 보존하고 최소 변경으로 작업할 것.
3. 사용자 입력 사실이 아닌 가격, 할인율, 평점, 판매량, 사용 후기, 제품 성능을 생성하거나 확정하지 말 것.
4. Product Lock, 광고·저작권·개인정보·컴플라이언스 게이트를 무력화하지 말 것.
5. 유료 영상/이미지/TTS API 호출과 외부 플랫폼 게시는 기본 OFF. 명시적 승인과 비용 상한이 있어야 함.
6. 토큰, 접근 코드, 사용자 사진, 민감 데이터, `.env` 파일을 커밋하거나 보고서에 노출하지 말 것.
7. 테스트는 우선 오프라인 fixture/mocks 사용. 실패를 숨기거나 자동으로 PASS로 바꾸지 말 것.
8. 구현 끝에는 **변경 파일 / 테스트 명령 및 실제 결과 / 미검증 영역 / 비용 영향 / 롤백**을 요약할 것.
9. 브랜치/PR 단위로 변경하고 기본 브랜치 병합 및 실제 배포는 사용자 승인 후 수행할 것.

## 우선 작업
`docs/AI_TEAM_WORKFLOW.md`의 1차 백로그를 참고하되, 시작 전 Issue의 수용 기준을 확인. 작업이 명확하지 않으면 근거·대안을 정리할 것.

## 검증 기준
- 최소: `python -m compileall -q shortsmaker`.
- 변경 영향 있는 테스트: `python -m pytest -q <대상 테스트>`.
- 최종 코드 검증: 가능하면 `python -m pytest -q` 및 결과 기록.
- 렌더링/영상 품질/플랫폼 게시의 실검증은 단위 테스트만으로 대체할 수 없음.
