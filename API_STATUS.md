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
| google (Gemini) | ✅ 인증 OK (환경 자격 증명, proxy-injected) · ❌ **결제 크레딧 소진(402)** | gemini-3.8-flash (+ 3.1-flash-lite). `gemini-2.5-*` 는 신규 사용자에게 종료(404) | json, vision, video_understanding, youtube_url | 모델 목록 조회 200, 생성 호출은 402 로 거절 | - | 402 prepayment credits depleted → AI Studio 에서 결제/충전 필요 |
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
