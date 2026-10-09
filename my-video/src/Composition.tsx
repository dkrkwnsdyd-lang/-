import { AbsoluteFill, CalculateMetadataFunction, Composition } from "remotion";
import { FONT } from "./fonts";

type Props = {};

const calculateMetadata: CalculateMetadataFunction<Props> = () => {
  return {};
};

export const MyComposition = () => {
  return (
    <Composition
      id="MyComp"
      component={MyComponent}
      durationInFrames={60}
      fps={30}
      width={1280}
      height={720}
      calculateMetadata={calculateMetadata}
    />
  );
};

export const MyComponent: React.FC<Props> = () => {
  return (
    <AbsoluteFill
      style={{
        backgroundColor: "white",
        justifyContent: "center",
        alignItems: "center",
        fontFamily: FONT,
        fontSize: 96,
        fontWeight: 800,
      }}
    >
      프리텐다드 폰트 테스트
    </AbsoluteFill>
  );
};
