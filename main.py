"""MCQ Video Generator — raw question text to a narrated walkthrough video.

Pipeline per question: structure raw text into JSON (AI) -> REVIEW GATE
(content lead edits/approves, sees the diagram rendered live) -> narrate
(ElevenLabs) + render diagram stages (schemdraw/RDKit) + render video
(Playwright + ffmpeg).

Runs on http://localhost:7864
"""

import io
import json
import os
import secrets
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from PIL import Image

load_dotenv()

from services.diagrams import render_circuit_stages, render_molecule
from services.extract import extract_document
from services.images import extract_diagrams
from services.render import render_video
from services.split import split_questions
from services.structure import IMAGE_ONLY_PLACEHOLDER, structure_question
from services.tts import DEFAULT_VOICE_ID, list_voices

# Only enforced when deployed with APP_PASSWORD set (e.g. on a public host) —
# local dev over localhost stays password-free.
_basic_auth = HTTPBasic(auto_error=False)


def require_auth(credentials: HTTPBasicCredentials = Depends(_basic_auth)) -> None:
    app_password = os.getenv("APP_PASSWORD")
    if not app_password:
        return
    app_username = os.getenv("APP_USERNAME", "pw")
    valid = credentials is not None and secrets.compare_digest(
        credentials.username, app_username
    ) and secrets.compare_digest(credentials.password, app_password)
    if not valid:
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})


app = FastAPI(title="MCQ Video Generator", dependencies=[Depends(require_auth)])
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BASE_DIR = Path(__file__).parent
JOBS_DIR = BASE_DIR / "jobs"
JOBS_DIR.mkdir(exist_ok=True)

JOBS: dict[str, dict] = {}


def log(job: dict, msg: str) -> None:
    job["log"].append({"ts": datetime.now().isoformat(timespec="seconds"), "message": msg})


def create_job(raw_text: str, images: list[bytes] | None = None, source: str = "manual") -> str:
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "id": job_id, "status": "queued", "log": [], "source": source,
        "raw_text": raw_text, "images": images or [], "structured": None, "error": None,
        "voice_id": DEFAULT_VOICE_ID,
    }
    threading.Thread(target=run_structuring, args=(job_id,), daemon=True).start()
    return job_id


def run_structuring(job_id: str) -> None:
    job = JOBS[job_id]
    try:
        job["status"] = "structuring"
        log(job, "Structuring raw question text with AI…")
        structured = structure_question(job["raw_text"], images=job.get("images") or None)
        job["structured"] = structured
        job["status"] = "review"
        log(job, "Structured ✅ — review the question, solution, and diagram before approving.")
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        log(job, f"ERROR: {e}")


def run_render(job_id: str) -> None:
    job = JOBS[job_id]
    job_dir = JOBS_DIR / job_id
    try:
        job["status"] = "rendering"
        log(job, "Generating narration and diagram stages…")
        out_path = render_video(job["structured"], job_dir, voice_id=job.get("voice_id", DEFAULT_VOICE_ID),
                                source_images=job.get("images") or None,
                                on_progress=lambda msg: log(job, msg))
        job["video_path"] = out_path
        job["status"] = "done"
        log(job, "Done ✅")
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        log(job, f"ERROR: {e}")


@app.post("/api/generate")
async def api_generate(raw_text: str = Form(...)):
    job_id = create_job(raw_text, source="manual")
    return {"job_id": job_id}


@app.post("/api/upload_bank")
async def api_upload_bank(file: UploadFile = File(...)):
    bank_id = uuid.uuid4().hex[:12]
    bank_dir = JOBS_DIR / "_banks" / bank_id
    bank_dir.mkdir(parents=True)
    source_path = bank_dir / file.filename
    with source_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    extracted = extract_document(source_path)
    diagrams_by_page: dict[int, list[str]] = {}
    if source_path.suffix.lower() == ".pdf":
        diagrams_by_page = extract_diagrams(source_path, bank_dir / "diagrams")

    chunks = split_questions(extracted["text"])
    job_ids = []
    for i, chunk in enumerate(chunks):
        images = None
        if chunk["page"] is not None and chunk["page"] in diagrams_by_page:
            images = [Path(p).read_bytes() for p in diagrams_by_page[chunk["page"]]]
        job_id = create_job(chunk["text"], images=images, source=f"bank:{bank_id}#{i}")
        job_ids.append(job_id)

    if not job_ids:
        raise HTTPException(400, "no questions detected in this document")
    return {"bank_id": bank_id, "job_ids": job_ids, "count": len(job_ids)}


@app.post("/api/upload_image")
async def api_upload_image(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        im = Image.open(io.BytesIO(raw))
        im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "PNG")
        png_bytes = buf.getvalue()
    except Exception as e:
        raise HTTPException(400, f"could not read image: {e}")
    job_id = create_job(IMAGE_ONLY_PLACEHOLDER, images=[png_bytes], source=f"image:{file.filename}")
    return {"job_id": job_id}


@app.get("/api/jobs")
def api_jobs_list():
    summaries = []
    for job in JOBS.values():
        question = (job.get("structured") or {}).get("question") or job["raw_text"][:80]
        summaries.append({
            "id": job["id"], "status": job["status"], "source": job.get("source", "manual"),
            "question": question, "error": job.get("error"),
        })
    return {"jobs": summaries}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {k: v for k, v in job.items() if k not in ("raw_text", "images")}


@app.post("/api/jobs/{job_id}/update")
async def api_update(job_id: str, structured_json: str = Form(...)):
    job = JOBS.get(job_id)
    if not job or job.get("status") != "review":
        raise HTTPException(409, "job is not awaiting review")
    try:
        structured = json.loads(structured_json)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"invalid JSON: {e}")
    if "question" not in structured or "options" not in structured:
        raise HTTPException(400, "structured JSON missing required fields")
    job["structured"] = structured
    log(job, "Reviewer edited the structured question.")
    return {"ok": True}


@app.get("/api/jobs/{job_id}/diagram_preview")
def api_diagram_preview(job_id: str):
    """Renders the CURRENT diagram spec through the exact same code used at
    final render time, so the reviewer approves what will actually appear in
    the video, not a JSON blob."""
    job = JOBS.get(job_id)
    if not job or not job.get("structured"):
        raise HTTPException(404, "job or structured data not found")
    diagram = job["structured"].get("diagram") or {"type": "none"}
    preview_dir = JOBS_DIR / job_id / "preview"
    if diagram.get("type") == "circuit":
        paths = render_circuit_stages(diagram["spec"], preview_dir)
        svg_path = paths[-1]
    elif diagram.get("type") == "molecule":
        svg_path = render_molecule(diagram["spec"], preview_dir)
    elif diagram.get("type") == "image":
        images = job.get("images") or []
        if not images:
            return Response(status_code=204)
        return Response(content=images[0], media_type="image/png")
    else:
        return Response(status_code=204)
    data = Path(svg_path).read_bytes()
    media_type = "image/svg+xml" if svg_path.endswith(".svg") else "image/png"
    return Response(content=data, media_type=media_type)


@app.get("/api/voices")
def api_voices():
    return {"voices": list_voices()}


@app.post("/api/jobs/{job_id}/approve")
async def api_approve(job_id: str, voice_id: str = Form(DEFAULT_VOICE_ID)):
    job = JOBS.get(job_id)
    if not job or job.get("status") != "review":
        raise HTTPException(409, "job is not awaiting review")
    job["voice_id"] = voice_id
    threading.Thread(target=run_render, args=(job_id,), daemon=True).start()
    return {"ok": True}


@app.get("/api/jobs/{job_id}/video")
def api_video(job_id: str):
    job = JOBS.get(job_id)
    if not job or not job.get("video_path") or not Path(job["video_path"]).exists():
        raise HTTPException(404, "video not ready")
    return FileResponse(job["video_path"], media_type="video/mp4",
                        filename=f"{job_id}.mp4")


@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/app", response_class=HTMLResponse)
def app_ui():
    return (BASE_DIR / "static" / "app.html").read_text(encoding="utf-8")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 7864)))
