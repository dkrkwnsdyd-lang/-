import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {FONT} from './fonts';

export const Scene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();

  // 제목이 아래에서 튀어오르며 등장
  const enter = spring({frame, fps, config: {damping: 200}});
  const titleY = interpolate(enter, [0, 1], [60, 0]);

  // 부제는 0.5초 뒤에 서서히 등장
  const subtitleOpacity = interpolate(frame, [15, 30], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // 마지막 0.5초 동안 전체 페이드아웃
  const exit = interpolate(frame, [durationInFrames - 15, durationInFrames], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: '#0f0f12',
        justifyContent: 'center',
        alignItems: 'center',
        fontFamily: FONT,
        color: 'white',
        opacity: exit,
      }}
    >
      <div style={{fontSize: 96, fontWeight: 800, opacity: enter, transform: `translateY(${titleY}px)`}}>
        3초 안에 멈추게 하는 법
      </div>
      <div style={{fontSize: 40, fontWeight: 500, marginTop: 24, color: '#a1a1aa', opacity: subtitleOpacity}}>
        Remotion + Pretendard
      </div>
    </AbsoluteFill>
  );
};
