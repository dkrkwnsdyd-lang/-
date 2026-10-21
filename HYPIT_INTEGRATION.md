# Hypit 연동 (선택 기능, 기본 비활성)

SHOP SHORTS AI V2의 기존 상품 분석, Product Lock, 판매 전략, Storyboard 및 컴플라이언스 파이프라인을 **유지**하면서, 결과를 Hypit용 Agent 제작 프로젝트로 넘깁니다.

## 지원하는 범위

- 기존 작업의 `result.json`에서 검증된 범위의 제품 식별·특징, 장면별 자막/음성 문구/샷 구성을 추출합니다.
- 사용자 PC에 있는 상품 사진만 로컬 준비 폴더의 `assets/`에 복사합니다. 인터넷에서 영상·사진을 내려받지 않습니다.
- `shop_shorts_manifest.json`과 `SHOP_SHORTS_HYPIT_BRIEF.md`를 만들고, Claude Code/Codex용 `/hypit` 제작 지시를 제공합니다.
- Hypit 설치, SVML/SVRUN 생성, 실제 MP4 렌더링은 **별도 단계**입니다. 이 기능만 실행해도 영상이 완성되는 것은 아닙니다.
- 기존 FFmpeg MP4, DB, 배포/게시 기능, QA 결과는 수정하지 않습니다.

## Windows PC에서 사용

1. 기존 SHOP SHORTS AI 웹/CLI로 상품 사진과 사실 기반 특징을 입력하고 작업을 생성합니다.
2. SHOP SHORTS AI 프로젝트 폴더에서 PowerShell을 열고 아래 명령을 입력합니다.

```powershell
python -m shortsmaker hypit-prepare output/v2/작업ID/result.json
```

3. 출력된 `output/v2/작업ID/hypit/` 폴더를 Claude Code 또는 Codex에서 엽니다.
4. Node.js와 Skill 설치 도구가 있는 경우, **Hypit 공식 안내에 따라** Skill을 설치합니다.

```powershell
npx skills add hypit-ai/hypit -g
hypit version --check
```

실행기 `hypit`이 없으면 Hypit 공식 Quickstart의 설치 절차를 사용하세요. Skill 설치와 실행기 설치는 별도 단계입니다.

5. 코딩 에이전트에게 다음을 요청합니다.

```text
/hypit 이 폴더의 SHOP_SHORTS_HYPIT_BRIEF.md 및 shop_shorts_manifest.json을 읽고,
상품 사진을 바꾸지 않는 한국어 9:16 쇼핑 숏폼 SVML/SVRUN 편집 프로젝트를 만들어줘.
먼저 생성형 모델 없이 가능한 로컬 렌더 방식을 시도하고,
유료 모델 호출이 필요하면 API, 예상 비용, 예산 승인부터 확인해.
```

6. 코딩 에이전트가 `.svrun` 파일과 Hypit Runtime을 구성한 뒤 `hypit plan 파일.svrun`으로 비용·실행 계획을 확인하고, 사용자가 승인한 경우에만 `hypit build 파일.svrun --follow`를 실행합니다.

## 주의 사항

- 본 연동은 **별도 Hypit 엔진으로의 자료 전달**이며, 기존 웹 UI 내에서 Hypit 렌더를 직접 실행하는 기능은 아닙니다.
- `QUALITY_FAIL`이나 `NEEDS_REVIEW` 작업도 개선 시안 작성을 위해 내보낼 수 있으나, 콘텐츠가 게시 가능하다는 뜻이 아닙니다. 제작 후 QA, 제휴 고지, 권리 검사를 **반드시 다시** 수행하세요.
- Hypit 참고 영상은 구조적 패턴만 분석하고, 제3자 영상·문장·얼굴·목소리를 허가 없이 복제하지 마세요.
- 원본 사진의 색상, 로고, 버튼 위치, 형태와 비율을 유지합니다. 입력하지 않은 효능·성능·리뷰·할인 등을 지어내지 않습니다.
- 실제 입력 사진이 누락되었다면 `missing_images`를 확인하고 경로를 복구하세요.
- `.env`/API 키를 제작 폴더나 GitHub에 넣지 마세요. 유료 API 호출은 사전 승인 필수입니다.
- Hypit 라이선스는 수정된 Apache 2.0 형태로, 제3자 대상 호스팅/재배포 관련 추가 제한이 있습니다. 개인 또는 단일 조직 내부 사용과 제3자용 다중 테넌트 SaaS는 조건이 다르므로 상용 배포 전에 공식 LICENSE를 확인하세요.

공식 참고: https://github.com/hypit-ai/hypit · https://github.com/hypit-ai/hypit/blob/main/docs/quickstart.md · https://github.com/hypit-ai/hypit/blob/main/LICENSE
