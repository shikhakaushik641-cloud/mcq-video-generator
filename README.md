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
- `static/index.html` — the review UI (paste text / upload image / upload bank)
