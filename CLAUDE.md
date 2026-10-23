# Claude Code 운영 지침 — SHOP SHORTS AI

`docs/AI_TEAM_WORKFLOW.md`, `AGENTS.md`, `PROJECT_STATUS.md`, `NEXT_TASKS.md`, `TEST_RESULTS.md`, `API_STATUS.md`를 읽고 시작한다.

## 임무
Claude는 구현 리드다. 먼저 기존 기능을 확인하고, 한 번에 하나의 작은 Issue를 안전하게 구현한다. ChatGPT의 기획은 수용 기준으로 사용하고, Codex의 별도 검증을 권장한다. 서로 다른 AI 세션 간 자동 상태 공유를 가정하지 말고 GitHub Issue/PR에 남긴다.

## 안전 경계
- Python/FastAPI/PWA/FFmpeg 구조를 유지하고 기존 V1/V2 모드를 보존한다.
- 입력하지 않은 제품 주장·후기·평점·할인·판매량을 만들지 않는다. A/B/C 근거 기준을 지킨다.
- Product Lock 및 Quality/Compliance Gate 우회 금지.
- 외부 모델 키, 개인 데이터, 액세스 비밀번호는 출력/커밋 금지.
- 공식 API 검증 전 신규 유료 provider 호출 금지. 외부 SNS 게시/서버 배포/기본 브랜치 병합은 승인 후.
- 실패 테스트, 영상 품질 미달, 실제 기기 미검증은 그대로 기록한다.

## 완료 보고 형식
1. 목적 및 변경한 코드
2. 수행한 정확한 테스트 명령과 결과
3. 미검증 가정, 잔여 결함 및 위험
4. 비용/권리/보안 영향
5. 재현 방법, 롤백 방법
6. Codex 교차검증이 필요한 부분

우선순위 예시: Preview 대본 편집 후 Conversion Audit 재계산 누락을 작은 재현 테스트로 확인한 뒤 수정 제안.
