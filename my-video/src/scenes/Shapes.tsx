// frames=180 size=1280x720
import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {Arrow, Callout, Circle, Heart, Pie, Rect, Star, Triangle} from '@remotion/shapes';
import {FONT} from '../font';

const GOLD = '#FFC93C';

// 갤러리 한 칸: 도형 + 컴포넌트 이름 + 움직이는 속성
const Cell = ({name, prop, delay, children}: {name: string; prop: string; delay: number; children: React.ReactNode}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const pop = spring({frame: f - delay, fps, config: {damping: 12}}); // 순서대로 톡 튀어나오기
  return (
    <div style={{width: 280, height: 270, display: 'flex', flexDirection: 'column', alignItems: 'center', transform: `scale(${pop})`}}>
      <div style={{height: 180, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>{children}</div>
      <div style={{color: GOLD, fontSize: 30, fontWeight: 900}}>{`<${name}>`}</div>
      <div style={{color: '#9fb0d0', fontSize: 20}}>{prop}</div>
    </div>
  );
};

const SceneBody = () => {
  const f = useCurrentFrame();
  const wave = (speed: number) => (Math.sin(f / speed) + 1) / 2; // 0~1 사이를 오가는 값

  // 로딩 링: 0 → 1 로 채워지는 진행률
  const progress = interpolate(f, [20, 150], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  // 별 꼭짓점 개수: 4 → 10 으로 늘어남 (정수여야 해서 Math.round)
  const points = Math.round(interpolate(f, [20, 150], [4, 10], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}));

  return (
    <AbsoluteFill style={{background: '#050914', fontFamily: FONT, alignItems: 'center', justifyContent: 'center'}}>
      <div style={{color: '#fff', fontSize: 40, fontWeight: 900, marginBottom: 10}}>@remotion/shapes</div>
      <div style={{display: 'flex', flexWrap: 'wrap', width: 1160, justifyContent: 'center'}}>
        <Cell name="Rect" prop={`cornerRadius=${Math.round(wave(15) * 60)}`} delay={0}>
          <Rect width={160} height={120} cornerRadius={wave(15) * 60} fill={GOLD} />
        </Cell>
        <Cell name="Circle" prop={`radius=${Math.round(50 + wave(12) * 25)}`} delay={4}>
          <Circle radius={50 + wave(12) * 25} fill="#5b8cff" />
        </Cell>
        <Cell name="Triangle" prop="direction='up'" delay={8}>
          <Triangle length={150} direction="up" fill="#7cf3c8" style={{transform: `rotate(${f * 2}deg)`}} />
        </Cell>
        <Cell name="Star" prop={`points=${points}`} delay={12}>
          <Star points={points} innerRadius={35} outerRadius={80} fill={GOLD} />
        </Cell>
        {/* Pie를 "링"으로: 채우기 없이 테두리만, closePath={false} */}
        <Cell name="Pie" prop={`progress=${progress.toFixed(2)}`} delay={16}>
          <div style={{position: 'relative', width: 160, height: 160, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
            <Pie radius={70} progress={1} closePath={false} fill="none" stroke="#1d2a48" strokeWidth={16} style={{position: 'absolute', overflow: 'visible'}} />
            <Pie radius={70} progress={progress} closePath={false} fill="none" stroke={GOLD} strokeWidth={16} strokeLinecap="round" style={{position: 'absolute', overflow: 'visible'}} />
            <div style={{color: '#fff', fontSize: 34, fontWeight: 900}}>{Math.round(progress * 100)}%</div>
          </div>
        </Cell>
        <Cell name="Heart" prop="height (두근두근)" delay={20}>
          <Heart height={110 + wave(5) * 20} fill="#ff5d7a" />
        </Cell>
        <Cell name="Arrow" prop="direction='right'" delay={24}>
          <Arrow length={170} headWidth={110} headLength={70} shaftWidth={45} cornerRadius={8} fill="#7cf3c8"
            style={{transform: `translateX(${wave(8) * 20 - 10}px)`}} />
        </Cell>
        <Cell name="Callout" prop="말풍선 · pointerDirection" delay={28}>
          <div style={{position: 'relative', display: 'flex', justifyContent: 'center'}}>
            <Callout width={200} height={100} cornerRadius={20} pointerLength={30} pointerDirection="down" fill="#fff" />
            <div style={{position: 'absolute', top: 30, color: '#050914', fontSize: 30, fontWeight: 900}}>안녕하세요!</div>
          </div>
        </Cell>
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
