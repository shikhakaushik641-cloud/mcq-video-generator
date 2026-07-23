import { Config } from "@remotion/cli/config";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// Remotion's own Chrome Headless Shell auto-download silently fails to land
// in its expected cache dir in this environment. Playwright (used by the
// sibling flashcard-generator project) already has a working headless-shell
// binary cached locally — reuse it instead of re-downloading.
// (Tried pointing this at Playwright's full chrome.exe instead, hoping for
// GPU-accelerated compositing on text/font-heavy frames — it fails to
// navigate under Remotion's headless invocation in this environment, so
// staying on chrome-headless-shell, which is the one that reliably works.)
const playwrightCacheDir = path.join(os.homedir(), "AppData", "Local", "ms-playwright");
if (fs.existsSync(playwrightCacheDir)) {
  const revisionDirs = fs.readdirSync(playwrightCacheDir).filter((d) => d.startsWith("chromium_headless_shell-"));
  for (const dir of revisionDirs) {
    const exePath = path.join(playwrightCacheDir, dir, "chrome-headless-shell-win64", "chrome-headless-shell.exe");
    if (fs.existsSync(exePath)) {
      Config.setBrowserExecutable(exePath);
      break;
    }
  }
}

Config.setVideoImageFormat("jpeg");
Config.setJpegQuality(80);
// Leave 2 cores free for the OS/other work; use the rest for parallel frame
// rendering — this is the single biggest lever on wall-clock render time.
Config.setConcurrency(Math.max(1, os.cpus().length - 2));
