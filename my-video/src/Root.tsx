import {Composition} from 'remotion';
import {Scene} from './Scene';

export const RemotionRoot = () => (
  <Composition id="Scene" component={Scene}
    durationInFrames={180} fps={30} width={1280} height={720} />
);
