# MCQ Video Generator

Turns a raw exam MCQ (pasted text, an uploaded image, or a docx/PDF question
bank) into a narrated, animated walkthrough video: AI structures the
question into a script + diagram spec, a human reviews and approves it, then
it's rendered into an mp4 with ElevenLabs narration (Hinglish, Indian accent)
and an animated diagram/solution panel.

## Pipeline

Raw question → **structure** (Claude/Azure OpenAI, vision-capable) → **review
gate** (human edits/approves, sees the diagram rendered live) → **render**
(ElevenLabs narration + schemdraw/RDKit diagrams + Playwright/ffmpeg video) → mp4.

## Setup

1. `pip install -r requirements.txt`
2. `playwright install chromium` (one-time browser download for frame capture)
3. `cd render && npm install && npm run build`
4. Copy `.env.example` to `.env` and fill in real keys:
   - `ANTHROPIC_API_KEY` (preferred) or `AZURE_OPENAI_*` (fallback)
   - `ELEVENLABS_API_KEY`
5. Run `start.bat` (Windows) or `python -m uvicorn main:app --host 127.0.0.1 --port 7864`
6. Open `http://localhost:7864`

## Project layout

- `main.py` — FastAPI app: job status machine, review/approve endpoints
- `services/` — structuring (AI), narration (ElevenLabs), diagram rendering
  (schemdraw/RDKit), document extraction, frame capture (Playwright) +
  video encode/mux (ffmpeg)
- `render/` — the React video composition, bundled by esbuild into a single
  static `dist/bundle.js` that the Python side loads in a headless browser
  and drives frame-by-frame
- `static/index.html` — the public landing page
- `static/app.html` — the actual tool UI (paste text / upload image / upload bank), served at `/app`

## Deploying so the team can reach it remotely

The app is containerized (`Dockerfile`) — Playwright's Chromium and the
`render/dist` bundle are baked into the image at build time, so the running
container needs no extra setup step. A `render.yaml` is included for
[Render](https://render.com):

1. Sign up at render.com and connect this GitHub repo.
2. New → Blueprint → pick this repo — it reads `render.yaml` and creates the
   web service on the **Standard** plan (2GB RAM; Playwright + RDKit +
   ffmpeg rendering concurrently needs more than the free/Starter tier's
   512MB, so don't drop below Standard without testing it holds up).
3. Fill in the env vars it prompts for (`ANTHROPIC_API_KEY` or the
   `AZURE_OPENAI_*` set, `ELEVENLABS_API_KEY`, and an `APP_PASSWORD` —
   every request can trigger paid AI/TTS calls, so this shouldn't be left
   open on a public URL). These are entered directly in Render's dashboard,
   never committed to the repo.
4. Deploy. The service comes up at `https://<name>.onrender.com` — share
   that URL with the team; they'll get an HTTP login prompt for
   `APP_USERNAME`/`APP_PASSWORD` before anything else loads.

Any other Docker-friendly host (Fly.io, a plain VM, etc.) works too — the
`Dockerfile` doesn't depend on Render specifically, just build it and run
the image with the same env vars, publishing the container's `$PORT`.

**Known limitation:** job state (`main.py`'s `JOBS` dict) and rendered
videos live in the container's memory/disk, not a database — a redeploy or
restart loses any in-progress or finished jobs. Fine for a small team using
it interactively and downloading videos as they finish; would need real
persistence (a DB + object storage) to survive restarts reliably.
