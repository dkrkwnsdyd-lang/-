# SHOP SHORTS AI — AI 개발팀 실행 매뉴얼 (2026-10-24)

## 실제로 연결된 부분
- GitHub: Issue(작업), PR(검토/승인), CI(문법·오프라인 테스트·전체 pytest)
- ChatGPT: 기획 및 Issue 수용 기준 작성
- `CLAUDE.md`: Claude Code 구현 지침
- `AGENTS.md`: Codex 검증 지침
- `scripts/ai_team.py`: 사용자의 로컬 PC에서 CLI가 설치된 경우 **명시적 동의하에** 단계별 자동 실행

**중요:** AI 계정과 CLI는 GitHub 연결만으로 실행되지 않는다. 이 문서는 계정, API 사용 권한, 상용 서비스 배포를 활성화하지 않는다.
Claude/Codex가 서로 토론하도록 자동으로 연결된 것이 아니라, 하나의 작업 명세와 로그를 전달하는 안전한 순차 워크플로다.

## 설치 전 점검 (Windows PowerShell, 프로젝트 폴더)
```powershell
python scripts/ai_team.py doctor
python scripts/ai_team.py prepare --task docs/tasks/issue-005-preview-audit.md
```
`doctor`의 `claude`, `codex`, `git` 항목을 확인한다. false면 각 CLI를 설치·로그인해야 한다. 설치된 CLI가 없더라도 `prepare`는 API를 호출하지 않으며 프롬프트 파일을 생성한다.

공식 문서(버전 변경 가능):
- Claude Code CLI: https://docs.anthropic.com/en/docs/claude-code/cli-usage
- Codex CLI: https://learn.chatgpt.com/docs/non-interactive-mode

## 실제 AI 개발팀 실행 (추가 요금 가능)
```powershell
python scripts/ai_team.py run --task docs/tasks/issue-005-preview-audit.md
# 위 명령은 dry-run이며 비용이 발생하지 않는다.

python scripts/ai_team.py run --task docs/tasks/issue-005-preview-audit.md --execute --approve-ai-cost
```
실행 시 깨끗한 Git 작업 디렉터리에서 `ai-team/<작업>-<날짜>` 브랜치를 만든 후
Claude Code 계획(읽기 전용) → Claude Code 구현(편집 권한) → Python 문법/전체 pytest → Codex 읽기 전용 코드 검토 순서로 진행한다.

- `--execute`와 `--approve-ai-cost` 둘 다 없으면 모델은 호출되지 않는다.
- CLI가 설치·로그인되어 있어야 하며, 플랜/구독/API 설정에 따라 추가 비용 또는 사용량 제한이 발생할 수 있다.
- 모델 응답/검증 결과는 로컬 `.ai-team/runs/`에 보관한다. 이 폴더는 `.gitignore` 대상이며, 기록에 개인/상품 데이터가 포함될 수 있으므로 외부 공유 주의.
- 실행 전에 `.env`·토큰/개인정보 파일 접근 범위를 사용자 PC의 권한 설정에서 제한한다. 자동화를 위한 비밀키의 대화/PR 출력 금지.
- 코드가 수정되더라도 **자동 push, PR 생성, 병합, 실배포, SNS 게시, 유료 영상/이미지 생성은 수행하지 않는다.**
- 테스트 FAIL 또는 Codex 검토 지적은 사용자가 PR을 승인하기 전 수정해야 한다.
- Reviewer의 텍스트 응답이 PASS여도 운영·실영상 품질·저작권 검토를 생략할 수 없다.

## 배포 단계
1. 테스트 PASS + 코드 리뷰 + 실제 사용자 시청 검수
2. GitHub PR 변경파일/보안/권리/비용 검토
3. 사용자 승인 후 병합
4. 별도 승인 후 스테이징 배포, 테스트 영상 1개 제작
5. 결과 확인 후 프로덕션 배포 및 상태 기록

## 재사용
TouchPilot에 적용할 때는 **실제 업무 앱의 접근권한·사람 승인·오류 복구·기기 테스트**를 별도 강화한다.
주식 자동매매에 적용할 때는 **실계좌 주문 OFF, 모의매매, 손실 한도, 주문 전 승인, 감사 로그**가 필수다.
이 저장소의 쇼츠 품질 검사만으로 이들 고위험 프로젝트의 승인 절차를 대신하지 않는다.
