# CLAUDE.md

이 저장소의 주 작업은 **Remotion으로 영상(릴스·예제 영상)을 만드는 것**이다. 사용자와는 한국어로 대화한다.

## 프로젝트 구조

- Remotion 프로젝트: `my-video/` (Remotion 4.0.534, React + TypeScript)
- `my-video/src/index.ts`: `registerRoot` 진입점
- `my-video/src/Root.tsx`: 예제마다 `<Composition>` 하나씩 등록 (id = 예제 이름)
- `my-video/src/scenes/*.tsx`: 예제 하나당 파일 하나. 각 파일은 `export const Scene` 을 내보내고, Root 에서 `import {Scene as 이름}` 으로 가져온다
- `my-video/src/font.ts`: Pretendard 폰트 로드, `FONT` 상수 export
- `my-video/public/fonts/PretendardVariable.woff2`: 폰트 파일 (CDN 대신 로컬 파일 사용)

## 영상 제작 규칙

- **폰트**: 항상 `import {FONT} from '../font';` 를 쓰고 `fontFamily: FONT` 로 적용한다. Pretendard 가변 폰트라 `fontWeight` 45~920 모두 쓸 수 있다.
- **브랜드 표시**: 모든 예제 영상 오른쪽 아래에 `CONNECT AI LAB` 을 넣는다. 크기와 위치는 화면 너비에 비례하게 잡는다.

  ```tsx
  const BrandMark = () => {
    const {width} = useVideoConfig();
    return (
      <div style={{position: 'absolute', right: Math.round(width * 0.02), bottom: Math.round(width * 0.015), fontFamily: FONT, fontWeight: 800,
        fontSize: Math.round(width / 60), letterSpacing: '0.16em', color: 'rgba(255,255,255,0.88)', textShadow: '0 1px 6px rgba(0,0,0,0.6)'}}>
        CONNECT AI LAB
      </div>
    );
  };
  ```

- **장면 구조**: `SceneBody`(본문)와 `BrandMark` 를 `AbsoluteFill` 로 겹쳐서 `Scene` 으로 export 한다.
- **파일 첫 줄**: `// frames=180 size=1280x720` 처럼 길이와 해상도를 주석으로 적는다.
- **기본값**: 1280×720, 30fps, 180프레임(6초). 릴스(세로)는 1080×1920 으로 만든다.
- **스타일**: 어두운 배경(`#050914` 계열)에 포인트 색 `#FFC93C`(GOLD)를 쓴다. 주석은 한글로 짧게, 각 애니메이션 값이 무엇을 하는지 적는다.
- **애니메이션**: `useCurrentFrame` + `interpolate`(항상 `extrapolateLeft/Right: 'clamp'`) + `spring` 을 쓴다. CSS transition 이나 `setTimeout` 은 쓰지 않는다.
- **패키지 추가**: `@remotion/*` 패키지는 `remotion` 과 **같은 정확한 버전**으로 설치한다. 예: `npm i @remotion/shapes@4.0.534 --save-exact`

## 확인과 렌더링

`my-video/` 에서 실행한다.

```bash
npx tsc --noEmit && npx eslint src        # 타입 검사와 lint
npx remotion studio                         # 미리보기 (로컬 PC)
npx remotion render <id> out/<id>.mp4        # mp4 렌더 (id 예: Shapes, ProductAd)
npx remotion still <id> out/f90.png --frame=90   # 특정 프레임 이미지
```

**클라우드 세션(Claude Code on the web)에서 렌더할 때**: Remotion이 브라우저를 받는 주소(remotion.media)와 jsDelivr CDN이 막혀 있다. 미리 설치된 headless shell 을 지정한다. 외부 이미지 주소(예: aicitybuilders.com)도 막혀 있으니, 확인용 렌더에는 임시 대체 이미지를 쓰고 커밋 전에 원래 코드로 되돌린다.

```bash
--browser-executable=/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell
```

## 작업 흐름

1. 코드를 작성하거나 사용자가 준 코드를 적용한다.
2. 타입 검사와 lint 를 통과시킨다.
3. mp4 로 렌더하고, 중간 프레임 하나를 이미지로 뽑아 직접 확인한 뒤 mp4 를 사용자에게 보낸다. 렌더 결과물은 저장소에 커밋하지 않는다(`out/` 은 gitignore).
4. 커밋하고 작업 브랜치에 푸시한다.
