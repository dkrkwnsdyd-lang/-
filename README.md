# 🛍️ SHOP SHORTS AI V2

> 📱 **폰에서 앱처럼 쓰기**: [MOBILE.md](MOBILE.md) — 홈 화면에 설치(PWA), 카메라 촬영, 공유하기, 접근 암호, Docker 배포

상품 **URL 또는 사진 몇 장**으로 **고품질 쇼핑 쇼츠(MASTER 1개 → 플랫폼별 버전 4개)** 를 만듭니다.
목표는 "기능이 많은 것"이 아니라 **사람이 만든 것처럼 자연스럽고, 제품이 정확하고, 바로 올릴 수 있는 영상 1개**입니다.

```bash
pip install -r requirements.txt
cp .env.example .env            # (선택) API 키 - 없어도 로컬 모드로 동작
python -m shortsmaker web       # http://127.0.0.1:8000  (스튜디오 / API Control Center: /control)

# 명령줄
python -m shortsmaker studio 정면.jpg 옆.jpg 사용장면.jpg \
    --name "무선 미니 마사지건" --features "4단계 강도 조절,USB-C 충전" \
    --problem "운동 끝나면 어깨가 뭉쳐요" --category 운동 --mode PRO
```

파이프라인: 사진 분석 → PRODUCT LOCK → 판매 각도 → 스토리(10패턴) → 훅 3후보 → 장면 설계(20필드) →
스토리보드 QA → 영상 라우터 → 멀티 테이크/베스트 테이크 → AI 편집(첫 3초 규칙) → 다이내믹 자막 →
렌더 → **최종 품질 QA (통과해야 COMPLETE)** → 플랫폼별 문구/CTA/음량 → **컴플라이언스(주장·고지·권리)** → export

- 결과: `output/v2/<작업ID>/` — `youtube.mp4`, `instagram.mp4`, `tiktok.mp4`, `threads.mp4`, `v*/MASTER.mp4`, `result.json`
- 현재 상태/다음 작업: `PROJECT_STATUS.md`, `NEXT_TASKS.md`, `API_STATUS.md`, `TEST_RESULTS.md`
- API 키가 없으면: 규칙 기반 기획 + 원본 사진 모션(제품 변형 0) + 자체 음악/효과음. 보이스오버/사람 등장 장면은 provider 연결 후.
- 카테고리를 입력하지 않으면 안전 판정이 UNKNOWN 이 되어 export 가 보류됩니다 (자동 GREEN 금지).

---

# (V1) 📱 숏폼 메이커 - 사진 슬라이드 영상 (`/classic`)

사진만 넣으면 **세로형 숏폼 영상(1080x1920)** 을 자동으로 만들고,
**유튜브 쇼츠 · 인스타그램 릴스 · 쓰레드 · 틱톡**에 한 번에 올릴 수 있는 도구입니다.

- 가로 사진(유튜브 캡처·썸네일 등)도 잘리지 않게 **흐린 배경 + 가운데 배치**
- 천천히 확대/이동하는 **켄번스 효과**, 사진 사이 **크로스페이드 전환**
- 상단 **제목**, 사진별 하단 **자막** (한글 지원)
- **배경음악** (없으면 무음 트랙 자동 추가)
- 유튜브 영상 주소를 넣으면 그 영상의 **썸네일을 사진으로 사용**
- 웹 화면(드래그&드롭) 또는 명령줄 둘 다 지원
- 결과물은 H.264/AAC mp4 → 4개 플랫폼 업로드 규격을 모두 만족

## 1. 설치

Python 3.10 이상이 필요합니다. ffmpeg 는 `imageio-ffmpeg` 가 자동으로 받아오므로 따로 설치하지 않아도 됩니다.

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

## 2. 사용법

### 웹 화면 (추천)

```bash
python -m shortsmaker web
```

브라우저에서 http://127.0.0.1:8000 접속 →
사진 끌어놓기 → 자막/제목 입력 → **영상 만들기** → 미리보기 확인 → 플랫폼 체크 → **올리기**

### 명령줄

```bash
# 영상만 만들기
python -m shortsmaker make 사진1.jpg 사진2.jpg 사진폴더/ \
    --title "오늘의 하이라이트" --captions "첫 장면|두 번째|마지막" \
    --bgm music.mp3 -o output/short.mp4

# 유튜브 영상 썸네일로 만들기
python -m shortsmaker make "https://youtu.be/영상ID" "https://youtu.be/다른영상ID" --title "추천 영상 모음"

# 만든 영상 올리기
python -m shortsmaker publish output/short.mp4 --title "오늘의 하이라이트" \
    --tags "여행,브이로그" --platforms youtube,instagram,threads,tiktok

# 만들기 + 전체 플랫폼 게시를 한 번에
python -m shortsmaker auto 사진폴더/ --title "오늘의 하이라이트" --platforms all
```

| 옵션 | 설명 | 기본값 |
| --- | --- | --- |
| `--seconds` | 사진 한 장당 시간(초) | 3 |
| `--transition` | 전환 효과 시간(초), 0 이면 컷 | 0.5 |
| `--fit` | `blur`(흐린 배경) / `crop`(꽉 채우기) | blur |
| `--no-zoom` | 확대/이동 효과 끄기 | - |
| `--privacy` | `public` / `unlisted` / `private` | public |

영상 길이는 기본 최대 60초로 맞춰집니다(사진이 많으면 한 장당 시간이 자동으로 줄어듦).

## 3. 플랫폼 연결 (최초 1회)

각 플랫폼은 공식 API 를 사용합니다. `config.yaml` 에 값을 넣으세요.

### 유튜브 쇼츠
1. [Google Cloud 콘솔](https://console.cloud.google.com/)에서 프로젝트 생성 → **YouTube Data API v3** 사용 설정
2. OAuth 동의 화면 구성 → 사용자 인증 정보 → **OAuth 클라이언트 ID (데스크톱 앱)** 생성 → JSON 을 `client_secret.json` 으로 저장
3. `python -m shortsmaker youtube-auth` 실행 → 브라우저에서 로그인 (토큰이 `youtube_token.json` 에 저장됨)

> 세로 영상 + 3분 이하이면 자동으로 쇼츠가 됩니다. 제목에 `#Shorts` 가 자동으로 붙습니다.
> 검수 전 Google Cloud 프로젝트에서 올린 영상은 비공개로 잠길 수 있습니다(YouTube API 감사 필요).

### 인스타그램 릴스
1. 인스타 계정을 **프로페셔널(비즈니스/크리에이터)** 로 전환
2. [Meta for Developers](https://developers.facebook.com/)에서 앱 생성 → Instagram API 추가
3. `instagram_content_publish` 권한이 있는 액세스 토큰과 IG 사용자 ID 를 `config.yaml` 의 `instagram` 에 입력

> 로컬 파일을 직접 업로드(resumable)하므로 공개 URL 이 없어도 됩니다.

### 쓰레드
1. Meta 앱에 **Threads API** 추가 → `threads_basic`, `threads_content_publish` 권한 토큰 발급
2. `config.yaml` 의 `threads` 에 토큰과 사용자 ID 입력
3. ⚠ Threads API 는 **영상을 공개 URL 로만** 받습니다. `general.public_base_url` 을 설정하세요.
   - 간단한 방법: 웹 화면 실행 후 `ngrok http 8000` → `public_base_url: https://xxxx.ngrok-free.app/outputs`

### 틱톡
1. [TikTok for Developers](https://developers.tiktok.com/)에서 앱 생성 → **Content Posting API** 추가 (`video.publish` 권한)
2. 사용자 액세스 토큰을 `config.yaml` 의 `tiktok.access_token` 에 입력

> 틱톡 심사(audit) 전 앱은 **나만 보기(SELF_ONLY)** 로만 게시됩니다.

## 4. 폴더 구조

```
shortsmaker/
  video.py          사진 → 세로 영상 (켄번스, 전환, 자막, BGM)
  sources.py        파일/폴더/이미지 URL/유튜브 썸네일 입력 처리
  platforms/        youtube.py · instagram.py · threads.py · tiktok.py
  web/              웹 화면 (FastAPI + HTML)
  cli.py            명령줄
tests/              pytest 테스트
```

테스트 실행: `python -m pytest`

## 5. 주의사항

- **저작권**: 다른 사람의 유튜브 영상 캡처·썸네일을 쓰면 저작권 문제로 영상이 삭제되거나 계정에 제재를 받을 수 있습니다. 본인이 권리를 가진 이미지를 사용하세요.
- 각 플랫폼의 API 이용 약관·게시 한도(예: 인스타그램 24시간 50개)를 지키세요.
- `config.yaml`, `client_secret.json`, `youtube_token.json` 은 비밀 정보라 `.gitignore` 에 포함되어 있습니다. 절대 공개 저장소에 올리지 마세요.
