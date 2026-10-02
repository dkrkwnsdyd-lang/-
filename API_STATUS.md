# API_STATUS

최종 확인: 2026-09-30

> 이 샌드박스에는 API 키가 하나도 없고, 외부 API 도메인(api.openai.com, api.groq.com, api.pexels.com 등)이
> 네트워크 정책으로 차단되어 있다. 그래서 **실제 외부 API 호출 테스트는 0건**이다.
> 아래 "Tested" 는 가짜(Fake) provider 로 라우터/폴백/비용 기록을 검증한 것만 뜻한다.

Gemini 키 넣는 법: 환경 설정 > API credentials(허용 웹사이트 `generativelanguage.googleapis.com`, 헤더 `x-goog-api-key`, 접두사 없음) 또는 환경 변수 `GEMINI_API_KEY`. 코드가 둘 다 자동 감지.

확인 방법: `python -m shortsmaker api-status` 또는 웹 `/control` (Test All / Test Provider / Test Fallback)
모델명은 `shortsmaker/providers/model_registry.yaml` 한 곳에만 있다. 사용 전 각 사의 모델 목록 API 로 ID 를 확인할 것.

| Provider | Connected | Model (registry) | Capabilities | Tested | Last Success | Error |
|---|---|---|---|---|---|---|
| openai | ❌ 키 없음 | gpt-5-mini (fallback gpt-4.1-mini) · tts: gpt-4o-mini-tts | json, vision, tts | 요청 형식만 구현, 실호출 X | - | 키 없음 + 도메인 차단 |
| google (Gemini) | ✅ 연결·호출 성공 (환경 자격 증명, proxy-injected) | gemini-3.8-flash (+ 3.1-flash-lite 예비). 2.5 계열은 이 키에서는 호출되나 신규 계정 종료 이력 있어 사용 안 함 | json, vision, video_understanding | ✅ 실호출 성공: 사진 분석, 대본, 근거 판정, 문구, 최종 시각 평가 (2026-09-30) | 2026-09-30 | 무료 여부는 API 로 알 수 없음 (`serviceTier: standard` 는 처리 등급). 사용량은 costs 테이블에 기록 (단가는 추정치) |
| google (Gemini) 사용량 | - | - | 영상 1개당 호출: Vision 분석 1~2, 대본 1~2, 근거 판정 2~4, 문구 1~2, 최종 평가 1~3(장면당 프레임 8장+자막 대조), 사진 보정 시 충실도 비교(보정본당 1~2) | ✅ 2026-09-30 실측: 영상 1개 $0.014~0.022 (추정 단가) | 2026-09-30 | 단가는 registry 추정치, 실제 청구 확인 필요 |
| groq | ❌ 키 없음 | llama-3.3-70b-versatile | json (저비용 전처리) | 실호출 X | - | 키 없음 + 도메인 차단 |
| elevenlabs | ❌ 키 없음 | eleven_multilingual_v2 | tts (한국어) | 실호출 X | - | ELEVENLABS_VOICE_ID 도 필요 |
| pexels | ❌ 키 없음 | videos/search | stock_video (B-roll 1순위) | 실호출 X | - | 파이프라인 미연결 (NEXT_TASKS) |
| pixabay | ❌ 키 없음 | videos | stock_video (B-roll 2순위) | 실호출 X | - | 파이프라인 미연결 |
| seedance | ❌ | (verify current id) · **enabled: false** | image_to_video, first_last_frame, reference_image | adapter 미구현(의도적) | - | 공식 API 문서 검증 전 호출 금지 |
| higgsfield | ❌ | (verify current id) · **enabled: false** | image_to_video, cinematic_camera | adapter 미구현(의도적) | - | 동일 |
| google_video (Veo) | ❌ | (verify current id) · **enabled: false** | text/image_to_video, first_last_frame | adapter 미구현(의도적) | - | 동일 |
| local: rule_director_v1 | ✅ | 규칙 기반 기획/대본 | json | ✅ 16개 영상 | 2026-09-28 | - |
| local: image_motion_v2 | ✅ | 원본 사진 모션 렌더러 | image_to_video, product_lossless | ✅ 16개 영상 | 2026-09-28 | - |
| local: pixel_stats_v1 | ✅ | 사진 분석(색/선명도/제품 영역) | vision_basic | ✅ | 2026-09-28 | - |

## 업로드 API (기존 기능, V1)
| Platform | 방식 | 상태 |
|---|---|---|
| YouTube | Data API v3 videos.insert (OAuth) | 구현됨, 실계정 미검증 |
| Instagram | Graph API REELS + resumable upload | 구현됨, 실계정 미검증 |
| Threads | Threads API VIDEO (공개 URL 필요) | 구현됨, 실계정 미검증 |
| TikTok | Content Posting API FILE_UPLOAD | 구현됨, 실계정 미검증 (심사 전 SELF_ONLY) |

## 정리된 것 (API/모델 정비)
- 종료/폐기 API: 코드에 없음 (기존 코드가 V1 뿐이라 정리 대상 없음)
- Naver 쇼핑 검색 API 의존 코드: 없음. 상품 URL 은 공개 메타데이터(og:, JSON-LD)만 읽고, 실패 시 사진+수동 입력.
- Coupang: Seller API / Partners API / 상품 페이지 import 를 구분해서 아직 어느 것도 연동하지 않음 (NEXT_TASKS).
- 비공식 endpoint 사용: 없음. 영상 생성 provider 는 추측 endpoint 로 유료 호출하지 않도록 비활성.


## 쿠팡 파트너스 Open API (2026-10-03)
- 연결: `studio/coupang.py` (HMAC 서명, 상품 검색). 키: `.env` 의 `COUPANG_ACCESS_KEY` / `COUPANG_SECRET_KEY`
- 사용 범위(사용자 결정): **이미지 사용 안 함**(응답 이미지 필드를 읽지도 저장하지도 않음), 정보(상품명/카테고리/가격/배송표시/링크)는 쇼츠 제작에만, 별도 저장소 없음(메모리 캐시 10분)
- 가격: 조회 시각 기록, 24시간 지나면 사실 근거에서 제외
- **검증 상태: 미검증.** 서명 방식·검색 주소는 공식 문서로 확인하지 못했다(개발 환경에서 문서/쿠팡 서버 접속 차단). 사용자 PC 에서 `python -m shortsmaker coupang-check` 로 확인 필요. 약관상 정보 사용 범위는 사용자가 확인
