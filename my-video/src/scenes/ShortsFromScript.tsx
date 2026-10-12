// frames=대본 길이에 따라 자동 size=1080x1920
// 대본 JSON(분석기 형식) → 세로 숏츠 영상. 렌더할 때 --props=대본.json 으로 내용만 바꾼다.
import {
  AbsoluteFill,
  Audio,
  CalculateMetadataFunction,
  Img,
  interpolate,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {FONT} from '../font';

const GOLD = '#FFC93C';
const FPS = 30;
const FALLBACK_SCENE_SEC = 4; // time 을 읽을 수 없을 때 장면당 길이

export type ScriptScene = {
  sceneNumber?: number;
  time?: string; // 예: "0:00 - 0:03"
  narration: string; // 아래쪽 자막으로 한 단어씩 나타남
  caption?: string; // 가운데 큰 키워드
  visual?: string; // 연출 메모 (화면에는 안 나옴)
  sfx?: string; // 효과음 메모 (화면에는 안 나옴)
  image?: string; // 배경 이미지: public/ 안의 경로 또는 https 주소
};

export type ShortsScript = {
  title: string; // 화면 위에 고정되는 제목
  scenes: ScriptScene[];
  audio?: string; // 내레이션/BGM 파일: public/ 안의 경로 또는 https 주소
};

type Timed = ScriptScene & {from: number; duration: number};

const toSrc = (src: string) => (/^https?:\/\//.test(src) ? src : staticFile(src));

// "0:03" → 3초
const parseClock = (s: string) => {
  const [m, sec] = s.split(':');
  return Number(m) * 60 + Number(sec);
};

// 각 장면의 시작 프레임과 길이 계산. time 이 이상하면 장면당 4초로 대체
export const layoutScenes = (scenes: ScriptScene[], fps = FPS): Timed[] => {
  let cursor = 0;
  return scenes.map((s) => {
    const clocks = s.time?.match(/\d+:\d+(?:\.\d+)?/g);
    let sec = FALLBACK_SCENE_SEC;
    if (clocks && clocks.length >= 2) {
      const len = parseClock(clocks[1]) - parseClock(clocks[0]);
      if (len > 0) sec = len;
    }
    const duration = Math.max(1, Math.round(sec * fps));
    const timed = {...s, from: cursor, duration};
    cursor += duration;
    return timed;
  });
};

export const calculateShortsMetadata: CalculateMetadataFunction<ShortsScript> = ({props}) => {
  const timed = layoutScenes(props.scenes);
  const last = timed[timed.length - 1];
  return {durationInFrames: last ? last.from + last.duration : FPS};
};

// 장면 배경: 이미지가 있으면 천천히 확대(켄 번스), 없으면 장면마다 색이 다른 그라데이션
const Background = ({scene, index}: {scene: Timed; index: number}) => {
  const f = useCurrentFrame();
  const zoom = interpolate(f, [0, scene.duration], [1.05, 1.18], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  if (scene.image) {
    return (
      <AbsoluteFill>
        <Img src={toSrc(scene.image)} style={{width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${zoom})`}} />
        {/* 글자가 잘 읽히도록 위아래를 어둡게 */}
        <AbsoluteFill style={{background: 'linear-gradient(180deg, rgba(5,9,20,0.75) 0%, rgba(5,9,20,0.15) 40%, rgba(5,9,20,0.85) 100%)'}} />
      </AbsoluteFill>
    );
  }
  const hue = (220 + index * 38) % 360; // 장면마다 색상환을 38도씩 이동
  const drift = interpolate(f, [0, scene.duration], [0, 12], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(circle at ${30 + drift}% ${35 + drift}%, hsl(${hue} 70% 32%) 0%, hsl(${hue} 60% 12%) 55%, #050914 100%)`,
      }}
    />
  );
};

// 장면 하나: 가운데 키워드가 튀어나오고, 아래 내레이션이 한 단어씩 나타남
const SceneView = ({scene, index}: {scene: Timed; index: number}) => {
  const f = useCurrentFrame();
  const {fps, width} = useVideoConfig();

  // 장면 시작 시 아래에서 위로 살짝 올라오며 등장
  const enter = spring({frame: f, fps, config: {damping: 14}});
  // 키워드는 0.15초 뒤에 톡 튀어나오기
  const pop = spring({frame: f - 4, fps, config: {damping: 9}});

  const words = scene.narration.split(/\s+/).filter(Boolean);
  // 장면 길이의 앞 70% 동안 단어를 순서대로 공개
  const revealEnd = Math.max(1, scene.duration * 0.7);
  const shown = interpolate(f, [2, revealEnd], [0, words.length], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

  return (
    <AbsoluteFill>
      <Background scene={scene} index={index} />

      {scene.caption ? (
        <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', top: -width * 0.12}}>
          <div
            style={{
              transform: `scale(${pop}) rotate(${(1 - pop) * -6}deg)`,
              background: GOLD,
              color: '#050914',
              fontFamily: FONT,
              fontWeight: 900,
              fontSize: width * 0.105,
              lineHeight: 1.15,
              padding: `${width * 0.02}px ${width * 0.045}px`,
              borderRadius: width * 0.03,
              maxWidth: width * 0.86,
              textAlign: 'center',
              wordBreak: 'keep-all', // 한글이 글자 중간에서 끊기지 않게
              boxShadow: '0 20px 50px rgba(0,0,0,0.45)',
            }}
          >
            {scene.caption}
          </div>
        </AbsoluteFill>
      ) : null}

      {/* 내레이션 자막: 숏츠 하단 UI(좋아요·댓글 버튼)에 안 가리도록 화면 64~80% 높이에 둔다 */}
      <div
        style={{
          position: 'absolute',
          left: width * 0.07,
          right: width * 0.07,
          top: '64%',
          textAlign: 'center',
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: width * 0.062,
          lineHeight: 1.35,
          color: '#fff',
          wordBreak: 'keep-all',
          textShadow: '0 4px 14px rgba(0,0,0,0.75)',
          opacity: enter,
          transform: `translateY(${(1 - enter) * 40}px)`,
        }}
      >
        {words.map((w, i) => {
          const visible = shown - i; // 1 이상이면 읽은 단어, 0~1 사이면 지금 읽는 단어
          const isCurrent = visible > 0 && visible < 1;
          return (
            <span
              key={i}
              style={{
                // 노래방 방식: 아직 안 읽은 단어도 흐리게 보여서 줄 배치가 흔들리지 않음
                opacity: interpolate(visible, [0, 1], [0.35, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}),
                color: isCurrent ? GOLD : '#fff', // 지금 읽는 단어만 금색
              }}
            >
              {w}{' '}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// 화면 위 고정 제목 + 진행 막대
const TopBar = ({title, total}: {title: string; total: number}) => {
  const f = useCurrentFrame();
  const {width} = useVideoConfig();
  const progress = interpolate(f, [0, total], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <>
      <div style={{position: 'absolute', top: 0, left: 0, height: width * 0.012, width: `${progress * 100}%`, background: GOLD}} />
      <div
        style={{
          position: 'absolute',
          top: width * 0.11,
          left: width * 0.06,
          right: width * 0.06,
          textAlign: 'center',
          fontFamily: FONT,
          fontWeight: 900,
          fontSize: width * 0.07,
          lineHeight: 1.2,
          color: '#fff',
          wordBreak: 'keep-all',
          WebkitTextStroke: `${width * 0.004}px #050914`,
          paintOrder: 'stroke fill',
          textShadow: '0 6px 18px rgba(0,0,0,0.6)',
        }}
      >
        {title}
      </div>
    </>
  );
};

const SceneBody = ({title, scenes, audio}: ShortsScript) => {
  const timed = layoutScenes(scenes);
  const last = timed[timed.length - 1];
  const total = last ? last.from + last.duration : 1;
  return (
    <AbsoluteFill style={{background: '#050914'}}>
      {timed.map((s, i) => (
        <Sequence key={i} from={s.from} durationInFrames={s.duration}>
          <SceneView scene={s} index={i} />
        </Sequence>
      ))}
      <TopBar title={title} total={total} />
      {audio ? <Audio src={toSrc(audio)} /> : null}
    </AbsoluteFill>
  );
};

// ── 채널 표시: CONNECT AI LAB (모든 예제 공통 · 오른쪽 아래) ──
const BrandMark = () => {
  const {width} = useVideoConfig();
  return (
    <div style={{position: 'absolute', right: Math.round(width * 0.02), bottom: Math.round(width * 0.015), fontFamily: FONT, fontWeight: 800,
      fontSize: Math.round(width / 60), letterSpacing: '0.16em', color: 'rgba(255,255,255,0.88)', textShadow: '0 1px 6px rgba(0,0,0,0.6)'}}>
      CONNECT AI LAB
    </div>
  );
};

export const Scene = (props: ShortsScript) => (
  <AbsoluteFill>
    <SceneBody {...props} />
    <BrandMark />
  </AbsoluteFill>
);
