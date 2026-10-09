// frames=210 size=1280x720
import {AbsoluteFill, Img, interpolate, random, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {FONT} from '../font';

// ── 여기만 바꾸면 "캐릭터가 소개하는 내 제품 광고"가 돼요 ──
const BASE = 'https://www.aicitybuilders.com/video/remotion/assets/';
const CHARACTER = BASE + 'jay_char.png'; // 캐릭터 (400×694, 허리에서 잘린 이미지 → 화면 아래에 붙이기)
const PRODUCT = BASE + 'product_juice.png'; // 제품 (배경이 투명한 PNG, 400×900)
const BUBBLE = '이거 진짜 상큼해요!';
const PRODUCT_NAME = '생오렌지 주스';
const LOWER_THIRD = ['제이의 추천', 'CONNECT AI LAB'];
const ORANGE = '#FF8A00';
const BG = ['#FFF4DC', '#FFC56B']; // 배경 그라데이션 (밝은 → 제품색)

const CH = 600; // 캐릭터 높이
const CW = CH * (400 / 694);
const PH = 500; // 제품 높이
const PW = PH * (400 / 900);
const PX = 930; // 제품 가운데 x
const PY = 330; // 제품 가운데 y

// 과즙 방울: random(seed)로 방향·거리·크기 고정
const DROPS = new Array(16).fill(0).map((_, i) => ({
  angle: (i / 16) * Math.PI * 2 + random(`a${i}`) * 0.4,
  dist: 290 + random(`d${i}`) * 170,
  size: 14 + random(`s${i}`) * 30,
  color: ['#FFC400', '#ffffff', '#FF6A00'][i % 3],
}));

const SceneBody = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

  // 1) 캐릭터: 아래에서 뿅 (발밑 기준으로 커지기) + 숨쉬듯 살짝 움직임
  const charIn = spring({frame: f, fps, config: {damping: 10}});
  const breathe = 1 + Math.sin(f / 14) * 0.012;
  // 2) 말풍선: 캐릭터 다음에 톡
  const bubble = spring({frame: f - 22, fps, config: {damping: 9}});
  // 3) 제품: 오른쪽에서 미끄러져 들어오며 회전 → 착지 순간(62) 과즙 튀기
  const prod = spring({frame: f - 45, fps, config: {damping: 12}});
  const splash = interpolate(f, [60, 90], [0, 1], clamp);
  // 4) 하단 자막바(로어서드)
  const lower = spring({frame: f - 140, fps, config: {damping: 15}});

  return (
    <AbsoluteFill style={{fontFamily: FONT, overflow: 'hidden', background: `linear-gradient(135deg, ${BG[0]} 20%, ${BG[1]} 100%)`}}>
      {/* 제품 뒤 큰 원 (무대) */}
      <div style={{position: 'absolute', left: PX - 270, top: PY - 270, width: 540, height: 540, borderRadius: '50%', background: ORANGE,
        transform: `scale(${prod})`, boxShadow: 'inset 0 -30px 60px rgba(0,0,0,0.12)'}} />

      {/* 과즙 고리 3개: 제품 뒤에서 퍼지기 */}
      {[0, 1, 2].map((i) => {
        const p = interpolate(f, [60 + i * 6, 100 + i * 6], [0, 1], clamp);
        return <div key={i} style={{position: 'absolute', left: PX - 150, top: PY - 150, width: 300, height: 300, borderRadius: '50%',
          border: `${10 - i * 3}px solid #fff`, transform: `scale(${0.6 + p * 1.6})`, opacity: p > 0 ? 1 - p : 0}} />;
      })}
      {/* 제품 */}
      <Img src={PRODUCT} style={{position: 'absolute', left: PX - PW / 2, top: PY - PH / 2, width: PW, height: PH,
        transform: `translateX(${(1 - prod) * 700}px) rotate(${(1 - prod) * 40 + Math.sin(f / 20) * 2}deg)`,
        filter: 'drop-shadow(0 26px 30px rgba(120,50,0,0.35))'}} />
      {/* 과즙 방울: 제품 앞에서 바깥으로 튀기 */}
      {DROPS.map((d, i) => {
        const r = d.dist * Math.sqrt(splash); // 처음엔 빠르게, 나중엔 천천히
        return <div key={i} style={{position: 'absolute', left: PX + Math.cos(d.angle) * r - d.size / 2, top: PY + Math.sin(d.angle) * r - d.size / 2,
          width: d.size, height: d.size, borderRadius: '50%', background: d.color, opacity: splash > 0 ? interpolate(splash, [0, 0.6, 1], [1, 1, 0]) : 0, boxShadow: '0 4px 10px rgba(150,60,0,0.25)',
          transform: `scale(${1 - splash * 0.5})`}} />;
      })}

      <div style={{position: 'absolute', left: PX - 200, width: 400, top: PY + PH / 2 + 18, textAlign: 'center', fontSize: 40, fontWeight: 900,
        color: '#3B1E00', opacity: interpolate(f, [75, 90], [0, 1], clamp)}}>{PRODUCT_NAME}</div>

      {/* 캐릭터: 화면 아래에 붙여서 잘린 허리가 안 보이게 */}
      <Img src={CHARACTER} style={{position: 'absolute', left: 120, bottom: 0, width: CW, height: CH, transformOrigin: '50% 100%',
        transform: `scale(${charIn}) scaleY(${breathe})`, filter: 'drop-shadow(0 10px 30px rgba(0,0,0,0.2))'}} />

      {/* 말풍선 (꼬리는 회전한 네모) */}
      <div style={{position: 'absolute', left: 310, top: 56, transformOrigin: '0% 100%', transform: `scale(${bubble})`}}>
        <div style={{position: 'relative', background: '#fff', borderRadius: 28, padding: '18px 30px', fontSize: 38, fontWeight: 900, color: '#222',
          boxShadow: '0 12px 30px rgba(150,70,0,0.25)', whiteSpace: 'nowrap'}}>
          {BUBBLE}
          <div style={{position: 'absolute', left: 34, bottom: -12, width: 28, height: 28, background: '#fff', transform: 'rotate(45deg)'}} />
        </div>
      </div>

      {/* 로어서드: 색 띠가 왼쪽에서 늘어나며 글자 등장 */}
      <div style={{position: 'absolute', left: 40, bottom: 44, display: 'flex', alignItems: 'stretch', clipPath: `inset(0 ${(1 - lower) * 100}% 0 0)`}}>
        <div style={{background: ORANGE, color: '#fff', fontSize: 30, fontWeight: 900, padding: '10px 22px'}}>{LOWER_THIRD[0]}</div>
        <div style={{background: '#1B1B1B', color: '#fff', fontSize: 24, fontWeight: 800, letterSpacing: '0.16em', padding: '10px 22px',
          display: 'flex', alignItems: 'center'}}>{LOWER_THIRD[1]}</div>
      </div>
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

export const Scene = () => (
  <AbsoluteFill>
    <SceneBody />
    <BrandMark />
  </AbsoluteFill>
);
