import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { BlockMath } from "react-katex";
import "katex/dist/katex.min.css";
import type { MCQProps, PanelItem } from "./types";

const secondsToFrames = (s: number, fps: number) => Math.max(1, Math.round(s * fps));

const assetSrc = (p: string) => (p.startsWith("/") || p.includes("://") ? p : staticFile(p));

const ANNOTATION_FONT = "'Lucida Handwriting', cursive";
const ANNOTATION_SIZE = 19;
const ANNOTATION_COLOR = "#111111";

/** Reveals `text` a character at a time rather than fading in as one typed
 * block, so the board notes read as being hand-written live while the
 * teacher talks, not as text that's already there. Finishes writing partway
 * through the item's own audio window (not at the very end) so the note has
 * time to sit on screen while still being spoken about. */
const HandwrittenText: React.FC<{ text: string; localFrame: number; frames: number }> = ({
  text,
  localFrame,
  frames,
}) => {
  const writeFrames = Math.max(1, Math.min(frames * 0.6, text.length * 2.2));
  const progress = interpolate(localFrame, [0, writeFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return <>{text.slice(0, Math.round(text.length * progress))}</>;
};

type TextPart = { text: string; phraseIndex?: number };

/** Splits `text` on each of `keyPhrases` in order (phrases are matched
 * left-to-right from where the previous match ended, so repeated substrings
 * resolve to the right occurrence). Phrases not found are skipped. */
const splitOnPhrases = (text: string, keyPhrases: string[]): TextPart[] => {
  const parts: TextPart[] = [];
  let cursor = 0;
  let phraseIndex = 0;
  for (const phrase of keyPhrases) {
    if (!phrase) continue;
    const idx = text.indexOf(phrase, cursor);
    if (idx === -1) continue;
    if (idx > cursor) parts.push({ text: text.slice(cursor, idx) });
    parts.push({ text: phrase, phraseIndex: phraseIndex++ });
    cursor = idx + phrase.length;
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor) });
  return parts;
};

/** Underlines each key phrase in turn, spread across the question-reading
 * audio's duration — like a teacher's pointing finger moving through the
 * question as they talk through it, not one single fixed underline. */
const AnnotatedQuestionText: React.FC<{
  text: string;
  keyPhrases: string[];
  questionFrom: number;
  questionFrames: number;
}> = ({ text, keyPhrases, questionFrom, questionFrames }) => {
  const frame = useCurrentFrame();
  const parts = splitOnPhrases(text, keyPhrases);
  const n = parts.filter((p) => p.phraseIndex !== undefined).length;
  if (n === 0) return <>{text}</>;

  return (
    <>
      {parts.map((part, i) => {
        if (part.phraseIndex === undefined) {
          return <React.Fragment key={i}>{part.text}</React.Fragment>;
        }
        const t = n === 1 ? 0.3 : 0.15 + (0.7 * part.phraseIndex) / (n - 1);
        const revealFrame = questionFrom + Math.round(questionFrames * t);
        const progress = interpolate(frame, [revealFrame, revealFrame + 15], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        return (
          <span key={i} style={{ position: "relative", display: "inline-block" }}>
            {part.text}
            <svg
              style={{ position: "absolute", left: 0, bottom: -6, width: "100%", height: 8 }}
              viewBox="0 0 100 8"
              preserveAspectRatio="none"
            >
              <line
                x1={0}
                y1={4}
                x2={100 * progress}
                y2={4}
                stroke="#d21f3c"
                strokeWidth={6}
                strokeLinecap="round"
              />
            </svg>
          </span>
        );
      })}
    </>
  );
};

const QuestionPanel: React.FC<{ props: MCQProps; questionFrom: number; questionFrames: number }> = ({
  props,
  questionFrom,
  questionFrames,
}) => (
  <div style={{ flex: 1, padding: 48, fontFamily: "Georgia, serif", fontSize: 28, color: "#111" }}>
    <div style={{ fontWeight: 700, fontSize: 22, marginBottom: 16 }}>[MCQ]</div>
    <div style={{ marginBottom: 32, lineHeight: 1.4 }}>
      <span style={{ fontWeight: 700 }}>#Q. </span>
      <AnnotatedQuestionText
        text={props.question.text}
        keyPhrases={props.question.keyPhrases}
        questionFrom={questionFrom}
        questionFrames={questionFrames}
      />
    </div>
    {props.question.options.map((opt, i) => (
      <div key={i} style={{ display: "flex", alignItems: "center", marginBottom: 20 }}>
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: "50%",
            background: "#111",
            color: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 700,
            marginRight: 20,
            flexShrink: 0,
          }}
        >
          {String.fromCharCode(65 + i)}
        </div>
        <div>{opt}</div>
      </div>
    ))}
  </div>
);

/** localFrame is frame-since-this-item-was-revealed; frames is this item's own
 * narration window. Once localFrame exceeds frames the stage index clamps to
 * the last (fully-labelled) image and simply holds — the item has finished
 * revealing but stays on screen, matching the sample video's cumulative
 * (additive, not replacing) panel layout. */
const DiagramStages: React.FC<{ images: string[]; localFrame: number; frames: number }> = ({
  images,
  localFrame,
  frames,
}) => {
  const perStage = frames / images.length;
  const stageIndex = Math.min(images.length - 1, Math.floor(localFrame / perStage));
  const stageLocalFrame = localFrame - stageIndex * perStage;
  const opacity = interpolate(stageLocalFrame, [0, 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <div style={{ position: "relative", width: "100%", height: 260 }}>
      {stageIndex > 0 && (
        <Img
          src={assetSrc(images[stageIndex - 1])}
          style={{ position: "absolute", width: "100%", height: "100%", objectFit: "contain" }}
        />
      )}
      <Img
        src={assetSrc(images[stageIndex])}
        style={{
          position: "absolute",
          width: "100%",
          height: "100%",
          objectFit: "contain",
          opacity,
        }}
      />
    </div>
  );
};

const PanelItemView: React.FC<{ item: PanelItem; localFrame: number; frames: number }> = ({
  item,
  localFrame,
  frames,
}) => {
  const opacity = interpolate(localFrame, [0, 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const annotationStyle: React.CSSProperties = {
    color: ANNOTATION_COLOR,
    fontFamily: ANNOTATION_FONT,
    fontSize: ANNOTATION_SIZE,
  };
  if (item.type === "diagram") {
    return (
      <div style={{ opacity }}>
        <DiagramStages images={item.images} localFrame={localFrame} frames={frames} />
      </div>
    );
  }
  return (
    <div style={{ opacity, marginBottom: 20, fontFamily: ANNOTATION_FONT }}>
      {item.type === "concept" && (
        <>
          <div style={{ color: ANNOTATION_COLOR, fontWeight: 700, fontSize: 21, textDecoration: "underline", marginBottom: 6 }}>
            Concept
          </div>
          {item.note && (
            <div style={annotationStyle}>
              <HandwrittenText text={item.note} localFrame={localFrame} frames={frames} />
            </div>
          )}
        </>
      )}
      {item.type === "step" && (
        <>
          {item.label && (
            <div style={{ color: ANNOTATION_COLOR, fontWeight: 700, fontSize: 21, marginBottom: 6, fontFamily: ANNOTATION_FONT }}>
              <HandwrittenText text={item.label} localFrame={localFrame} frames={frames} />
            </div>
          )}
          {item.note && (
            <div style={annotationStyle}>
              <HandwrittenText text={item.note} localFrame={localFrame} frames={frames} />
            </div>
          )}
          {item.latex && (
            <div style={{ color: ANNOTATION_COLOR, fontSize: 26, marginTop: item.note ? 8 : 0 }}>
              <BlockMath math={item.latex} />
            </div>
          )}
        </>
      )}
    </div>
  );
};

export const MCQVideo: React.FC<MCQProps> = (props) => {
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();
  const introFrames = secondsToFrames(props.intro.audio.durationS, fps);
  const questionFrames = secondsToFrames(props.question.audio.durationS, fps);
  const questionFrom = introFrames;

  let cursor = questionFrom + questionFrames;
  const panelItems = props.panel.map((item, i) => {
    const frames = secondsToFrames(item.audio.durationS, fps);
    const from = cursor;
    cursor += frames;
    return { item, from, frames, key: i };
  });

  // All layout below is authored in a fixed 1280x720 logical box and scaled
  // up to fill whatever the actual output resolution is (e.g. 1920x1080),
  // rather than rewriting every hardcoded px value proportionally.
  const { width, height } = useVideoConfig();
  const scale = Math.min(width / 1280, height / 720);

  return (
    <AbsoluteFill style={{ backgroundColor: "#ffffff" }}>
      <Sequence from={0} durationInFrames={introFrames} layout="none">
        <Audio src={assetSrc(props.intro.audio.path)} />
      </Sequence>
      <Sequence from={questionFrom} durationInFrames={questionFrames} layout="none">
        <Audio src={assetSrc(props.question.audio.path)} />
      </Sequence>
      {panelItems.map(({ item, from, frames, key }) => (
        <Sequence key={key} from={from} durationInFrames={frames} layout="none">
          <Audio src={assetSrc(item.audio.path)} />
        </Sequence>
      ))}
      <div style={{ width: 1280, height: 720, transform: `scale(${scale})`, transformOrigin: "top left" }}>
        <AbsoluteFill style={{ display: "flex", flexDirection: "row" }}>
          <QuestionPanel props={props} questionFrom={questionFrom} questionFrames={questionFrames} />
          <div style={{ flex: 1, padding: 48, display: "flex", flexDirection: "column" }}>
            {panelItems
              .filter(({ from }) => frame >= from)
              .map(({ item, from, frames, key }) => (
                <PanelItemView key={key} item={item} localFrame={frame - from} frames={frames} />
              ))}
          </div>
        </AbsoluteFill>
      </div>
    </AbsoluteFill>
  );
};
