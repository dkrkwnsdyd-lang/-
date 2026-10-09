import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";

export const FONT = "Pretendard";

loadFont({
  family: FONT,
  url: staticFile("fonts/PretendardVariable.woff2"),
  weight: "45 920",
  format: "woff2",
});
