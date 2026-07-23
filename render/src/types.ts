export type Audio = { path: string; durationS: number };

export type PanelItem =
  | { type: "concept"; note?: string; audio: Audio }
  | { type: "diagram"; images: string[]; audio: Audio }
  | { type: "step"; label?: string; latex?: string; note?: string; audio: Audio };

export type MCQProps = {
  fps: number;
  width: number;
  height: number;
  intro: { audio: Audio };
  question: {
    text: string;
    keyPhrases: string[];
    options: string[];
    audio: Audio;
  };
  panel: PanelItem[];
};
