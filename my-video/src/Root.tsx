import {Composition} from 'remotion';
import {Scene as Shapes} from './scenes/Shapes';
import {Scene as ProductAd} from './scenes/ProductAd';

// 예제마다 src/scenes/ 에 파일 하나, 여기에 Composition 하나씩 등록
export const RemotionRoot = () => (
  <>
    <Composition id="Shapes" component={Shapes}
      durationInFrames={180} fps={30} width={1280} height={720} />
    <Composition id="ProductAd" component={ProductAd}
      durationInFrames={210} fps={30} width={1280} height={720} />
  </>
);
