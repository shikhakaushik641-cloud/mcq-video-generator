import React from "react";
import { createRoot } from "react-dom/client";
import { MCQVideo } from "./MCQVideo";
import type { MCQProps } from "./types";

declare global {
  interface Window {
    __PROPS__: MCQProps;
    renderFrame: (frame: number) => void;
  }
}

const container = document.getElementById("root")!;
const root = createRoot(container);

// Mount once; each renderFrame() call just re-renders the same tree with a
// new `frame` prop — this is what replaces Remotion's per-frame lifecycle
// (see services/frame_capture.py, which calls this once per frame then
// screenshots the result).
root.render(<MCQVideo {...window.__PROPS__} frame={0} />);

window.renderFrame = (frame: number) => {
  root.render(<MCQVideo {...window.__PROPS__} frame={frame} />);
};
