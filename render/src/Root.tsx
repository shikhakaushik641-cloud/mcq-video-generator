import { Composition } from "remotion";
import { MCQVideo } from "./MCQVideo";
import type { MCQProps } from "./types";

const FPS = 30;

const secondsToFrames = (s: number, fps: number) => Math.max(1, Math.round(s * fps));

const totalFrames = (props: MCQProps) => {
  const fps = props.fps ?? FPS;
  let frames = secondsToFrames(props.intro.audio.durationS, fps);
  frames += secondsToFrames(props.question.audio.durationS, fps);
  for (const item of props.panel) {
    frames += secondsToFrames(item.audio.durationS, fps);
  }
  return frames;
};

const defaultProps: MCQProps = {
  fps: FPS,
  width: 1920,
  height: 1080,
  intro: { audio: { path: "", durationS: 4 } },
  question: {
    text: "Find the voltage across capacitors under DC conditions in the given circuit.",
    keyPhrases: ["under DC conditions"],
    options: [
      "V_C1 = 30V, V_C2 = 60V",
      "V_C1 = 30V, V_C2 = 40V",
      "V_C1 = 20V, V_C2 = 40V",
      "V_C1 = 20V, V_C2 = 60V",
    ],
    audio: { path: "", durationS: 5 },
  },
  panel: [],
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="MCQVideo"
      component={MCQVideo}
      fps={FPS}
      width={1920}
      height={1080}
      durationInFrames={150}
      defaultProps={defaultProps}
      calculateMetadata={async ({ props }) => ({
        durationInFrames: totalFrames(props),
        fps: props.fps ?? FPS,
        width: props.width ?? 1920,
        height: props.height ?? 1080,
      })}
    />
  );
};
