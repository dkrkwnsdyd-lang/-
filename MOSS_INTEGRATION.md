# MOSS-Image × SHOP SHORTS AI

## 현재 구현 범위 (기본 OFF)

- `/moss`에서 한국어 이미지 배경 스튜디오 접근. PC/모바일 사용 가능.
- `POST /api/moss/plan`은 배경 프롬프트와 이미지 생성 사양만 반환하며 **네트워크 호출이나 과금 없음**.
- `POST /api/moss/generate`는 `approve_paid=true` + 서버 환경 변수 `MOSS_API_KEY`가 모두 있을 때에만 MOSI 공식 API에 이미지 1장 요청.
- MOSS는 **텍스트 → 배경 이미지 생성**에만 사용. 실제 상품 사진은 원본 픽셀을 유지하면서 별도 사진 카드로 합성. 상품 정체성 보존을 위한 이미지-투-이미지 기능으로 오해하지 마세요.
- 배경·합성 썸네일·작업 메타데이터는 `output/moss/<작업ID>/`에 저장되며 기존 V2 마스터 영상이나 게시 내역에 자동 반영하지 않습니다.
- 게시 전 제품/주장/권리/제휴 고지 등 사람의 검수가 필수. 내보내기 결과는 `NEEDS_REVIEW`, `publishable=false`.

## Windows PC 준비

1. 기존 `SHOP SHORTS AI` 의존성을 설치하고, `MOSS_API_KEY`는 본인의 PC `.env`에만 추가합니다. 비밀 키를 GitHub·채팅·브라우저에 붙여넣지 않습니다.
2. `python -m shortsmaker web` 실행 후 `http://127.0.0.1:8000/moss`로 이동합니다.
3. 상품명, 실제 상품 사진, 배경 스타일, 근거가 있는 썸네일 제목을 입력합니다.
4. [무료 기획 확인]으로 프롬프트와 설정을 검토합니다. 이 단계는 과금되지 않습니다.
5. 이미지 생성이 필요하면 API 가격과 잔액을 먼저 확인하고, 1회 유료 호출에 동의한 뒤 생성합니다.

## CLI 기획만 하기 (무료)

```powershell
python -m shortsmaker moss-image --name "접이식 핸드폰 거치대" --photo "product.jpg" --headline "책상 정리" --scene "밝은 원목 책상, 아침 햇살" --style lifestyle
```

`output/moss/moss-plan.json` 생성. 이 명령은 MOSS에 요청하지 않습니다.

## CLI에서 기존 작업 결과 활용

```powershell
python -m shortsmaker moss-image --from-job output/v2/작업ID/result.json --out output/moss/상품1
```

V2 `result.json`에 있는 상품명 및 로컬 원본 사진을 자동 선택하고 기획 파일을 만듭니다. 실패 작업은 차단합니다.

## 실제 API 호출 (1회 요금 발생 가능)

```powershell
python -m shortsmaker moss-image --from-job output/v2/작업ID/result.json --out output/moss/상품1 --generate --approve-paid
```

`MOSS_API_KEY`가 없으면 요청을 보내지 않고 오류를 표시합니다. 가격은 가입한 MOSI 계정의 최신 요금에서 확인하세요. API 비용을 0원으로 가정하지 않습니다.

## Codex 확인 작업

1. `python -m pytest tests/test_moss_image.py -q` 실행.
2. `python -m shortsmaker moss-image --name "Test"` 실행 후 **과금/호출 없이** `moss-plan.json` 확인.
3. `.env` 없이 `--generate --approve-paid`를 실행했을 때 요청을 보내지 않고 실패하는지 확인.
4. `python -m shortsmaker web`, `/moss` 진입, 기획 버튼, 유료 동의 체크, 접근암호 차단 점검.
5. 실제 API 테스트는 예산 승인·키 확인 후에만 수행. 생성 1장으로 광고 배경, 제품 사진 불변, 한글 자막 확인.
6. 참조 이미지 결과의 과도한 객체나 글씨가 나오면 수동 검토 또는 배경 교체. 합성된 이미지를 자동 업로드/게시하지 않을 것.
7. Hypit 편집 파이프라인에 이미지를 활용하려면 검수한 `cover.png`를 **선택적으로** 에셋으로 추가할 것. 기존 QA PASS로 간주하지 말 것.

## 기술 근거 및 제한

- 공식 API: `POST https://api.mosi.cn/v1/images/generations`, 모델 `moss-image-sft-1.0` 또는 `moss-image-base-1.0`.
- 요청 `prompt`, `negative_prompt`, `size`, `n=1`, `response_format=url`로 보내며, 결과 이미지 URL은 `data[0].url`입니다.
- 720×1280은 9:16이며 양쪽 모두 16의 배수, 총 픽셀수 2,097,152 이하입니다.
- 공식 문서상 출력은 **텍스트→이미지**입니다. 실제 상품의 색/형태 보존을 위해 생성 배경 위에 별도 사진 카드로 합성합니다.
- 배경 모델의 글자·문구 품질에 의존하지 않고 제목은 원본 사진과 독립적으로 PIL로 작성합니다.
- 모델을 로컬에서 실행하려면 더 큰 GPU 메모리와 PyTorch/diffusers 환경이 필요합니다. 현재 통합은 로컬 모델 다운로드가 아닌 MOSI API 방식입니다.
- MOSI API 문서: https://platform.mosi.cn/en/docs/reference/images-generations/
- 가격 페이지: https://platform.mosi.cn/app/pricing/
- 모델 및 라이선스: https://github.com/OpenMOSS/MOSS-Image 및 https://huggingface.co/OpenMOSS-Team/MOSS-Image-SFT

## 보안

- `.env`, 키, 사용자 비밀은 커밋하지 않습니다. 생성 요청에서 환경 변수로만 키를 읽습니다.
- 다운로드 대상은 HTTPS만 허용, 사설 IP·localhost와 리다이렉트는 차단, 최대 20MB를 허용합니다.
- 웹 API는 기존 SHOP SHORTS AI 접근 암호를 그대로 적용합니다.
- 이 변경은 제휴 광고를 자동으로 발행하지 않습니다.
