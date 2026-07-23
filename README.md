# MCQ Video Generator

Turns a raw exam MCQ (pasted text, an uploaded image, or a docx/PDF question
bank) into a narrated, animated walkthrough video: AI structures the
question into a script + diagram spec, a human reviews and approves it, then
it's rendered into an mp4 with ElevenLabs narration (Hinglish, Indian accent)
and an animated diagram/solution panel.

## Pipeline

Raw question → **structure** (Claude/Azure OpenAI, vision-capable) → **review
gate** (human edits/approves, sees the diagram rendered live) → **render**
(ElevenLabs narration + schemdraw/RDKit diagrams + Remotion video) → mp4.

## Setup

1. `pip install -r requirements.txt`
2. `cd render && npm install`
3. Copy `.env.example` to `.env` and fill in real keys:
   - `ANTHROPIC_API_KEY` (preferred) or `AZURE_OPENAI_*` (fallback)
   - `ELEVENLABS_API_KEY`
4. Run `start.bat` (Windows) or `python -m uvicorn main:app --host 127.0.0.1 --port 7864`
5. Open `http://localhost:7864`

## Project layout

- `main.py` — FastAPI app: job status machine, review/approve endpoints
- `services/` — structuring (AI), narration (ElevenLabs), diagram rendering
  (schemdraw/RDKit), document extraction, Remotion render bridge
- `render/` — the Remotion (React) video composition
- `static/index.html` — the review UI (paste text / upload image / upload bank)

## Known issue: Remotion licensing

`render/` currently uses [Remotion](https://remotion.dev) to composite and
render the final video. Remotion's license is free only for individuals or
companies with ≤3 employees — production use by a larger company requires a
paid company license (see `remotion-dev/remotion`'s `LICENSE.md`). This
project is planned to move to a Playwright + ffmpeg based renderer (both
properly open-source, no company-size restriction) to remove that
dependency; until then, do not use this in production without either
purchasing a Remotion license or completing that migration.
