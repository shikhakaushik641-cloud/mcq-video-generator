"""Bridge from a structured question JSON to a rendered mp4.

Builds the narration segments + circuit diagram stages, assembles a
Remotion props.json, and shells out to `npx remotion render`. Kept as a
straight subprocess call (not a persistent Node service) since renders are
infrequent and CPU-heavy — matches flashcard-generator's synchronous,
one-job-at-a-time rendering model.
"""

import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable

from services.diagrams import render_circuit_stages, render_molecule
from services.tts import DEFAULT_VOICE_ID, narrate_segments

RENDER_DIR = Path(__file__).parent.parent / "render"
# At this environment's current measured rate (~150-165ms/frame), a long
# multi-step question (150-200s of narration, 5000+ frames) genuinely needs
# 12-15 minutes — 600s cut those off mid-render with a hard failure, not
# just a slow success. 1800s covers questions up to ~5-6 minutes of content.
RENDER_TIMEOUT_S = 1800

INTRO_LINE = (
    "Hello बच्चो! चलो अब हम इस question को solve करते हैं। "
    "इस question में हमें क्या करना है, ये देखते हैं।"
)


def _build_narration_segments(question: dict) -> list[dict]:
    question_read = (question.get("questionIntro") or {}).get("spoken") or question["question"]
    segments = [{"id": "intro", "text": INTRO_LINE}, {"id": "question", "text": question_read}]
    if question.get("concept"):
        segments.append({"id": "concept", "text": question["concept"]["spoken"]})
    diagram = question.get("diagram") or {"type": "none"}
    if diagram.get("type") != "none":
        segments.append({"id": "diagram", "text": diagram["spoken"]})
    for i, step in enumerate(question.get("solution_steps", [])):
        segments.append({"id": f"step{i}", "text": step["spoken"]})
    return segments


def _static_path(path: str | Path) -> str:
    """Path relative to render/public, as a forward-slash URL path (staticFile() convention)."""
    return os.path.relpath(path, RENDER_DIR / "public").replace(os.sep, "/")


def _audio_ref(narrated: dict) -> dict:
    return {"path": _static_path(narrated["path"]), "durationS": narrated["duration_s"]}


def build_props(question: dict, job_dir: str | Path, voice_id: str = DEFAULT_VOICE_ID,
                source_images: list[bytes] | None = None) -> dict:
    job_dir = Path(job_dir)
    audio_dir = job_dir / "audio"
    diagram_dir = job_dir / "diagrams"
    public_dir = RENDER_DIR / "public" / job_dir.name
    public_dir.mkdir(parents=True, exist_ok=True)

    narration = _build_narration_segments(question)
    narrated = {n["id"]: n for n in narrate_segments(narration, audio_dir, voice_id=voice_id)}

    for n in narrated.values():
        dest = public_dir / Path(n["path"]).name
        dest.write_bytes(Path(n["path"]).read_bytes())
        n["path"] = str(dest)

    diagram = question.get("diagram") or {"type": "none"}
    diagram_images: list[str] = []
    if diagram.get("type") == "circuit":
        stage_paths = render_circuit_stages(diagram["spec"], diagram_dir)
        for p in stage_paths:
            dest = public_dir / Path(p).name
            dest.write_bytes(Path(p).read_bytes())
            diagram_images.append(str(dest))
    elif diagram.get("type") == "molecule":
        p = render_molecule(diagram["spec"], diagram_dir)
        dest = public_dir / Path(p).name
        dest.write_bytes(Path(p).read_bytes())
        diagram_images = [str(dest)]
    elif diagram.get("type") == "image" and source_images:
        diagram_dir.mkdir(parents=True, exist_ok=True)
        src_path = diagram_dir / "figure.png"
        src_path.write_bytes(source_images[0])
        dest = public_dir / src_path.name
        dest.write_bytes(src_path.read_bytes())
        diagram_images = [str(dest)]

    panel = []
    if question.get("concept"):
        panel.append({"type": "concept", "note": question["concept"].get("note"), "audio": _audio_ref(narrated["concept"])})
    if diagram.get("type") != "none" and diagram_images:
        panel.append({
            "type": "diagram",
            "images": [_static_path(p) for p in diagram_images],
            "audio": _audio_ref(narrated["diagram"]),
        })
    for i, step in enumerate(question.get("solution_steps", [])):
        panel.append({
            "type": "step",
            "label": step.get("label"),
            "latex": step.get("latex"),
            "note": step.get("note"),
            "audio": _audio_ref(narrated[f"step{i}"]),
        })

    return {
        "fps": 30,
        "width": 1920,
        "height": 1080,
        "intro": {"audio": _audio_ref(narrated["intro"])},
        "question": {
            "text": question["question"],
            "keyPhrases": question.get("keyPhrases") or [],
            "options": question["options"],
            "audio": _audio_ref(narrated["question"]),
        },
        "panel": panel,
    }


_PROGRESS_RE = re.compile(r"Rendered (\d+)/(\d+)")


def render_video(question: dict, job_dir: str | Path, out_name: str = "video.mp4",
                 voice_id: str = DEFAULT_VOICE_ID, source_images: list[bytes] | None = None,
                 on_progress: Callable[[str], None] | None = None) -> str:
    """on_progress, if given, is called with a human-readable string at each
    ~10% frame-render milestone — a long multi-step question can take many
    minutes to render (proportional to its own narration length, not
    something a code fix shrinks), so surfacing real progress matters more
    than the total number: it's the difference between "still working" and
    "looks frozen"."""
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    props = build_props(question, job_dir, voice_id=voice_id, source_images=source_images)
    props_path = job_dir / "props.json"
    props_path.write_text(json.dumps(props, indent=2, ensure_ascii=False), encoding="utf-8")
    public_dir = RENDER_DIR / "public" / job_dir.name

    try:
        out_path = job_dir / out_name
        cmd = [
            "npx", "remotion", "render", "src/index.ts", "MCQVideo", str(out_path.resolve()),
            f"--props={props_path.resolve()}",
        ]
        process = subprocess.Popen(
            cmd, cwd=str(RENDER_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, shell=True, bufsize=1,
        )
        watchdog = threading.Timer(RENDER_TIMEOUT_S, process.kill)
        watchdog.start()
        lines: list[str] = []
        last_reported_pct = -1
        try:
            for line in process.stdout:
                lines.append(line)
                match = _PROGRESS_RE.search(line)
                if match and on_progress:
                    done, total = int(match.group(1)), int(match.group(2))
                    pct = (done * 100 // total) if total else 0
                    if pct >= last_reported_pct + 10:
                        last_reported_pct = pct - (pct % 10)
                        on_progress(f"Rendering video… {pct}% ({done}/{total} frames)")
            process.wait()
        finally:
            watchdog.cancel()

        log_path = job_dir / "render.log"
        log_path.write_text("".join(lines), encoding="utf-8")
        if process.returncode != 0:
            raise RuntimeError(f"remotion render failed (see {log_path}):\n{''.join(lines)[-2000:]}")
        return str(out_path)
    finally:
        # render/public is scratch space Remotion's bundler copies in full on
        # EVERY render — without this cleanup it accumulates every job's
        # assets forever and each subsequent render gets slower than the
        # last (this is what made renders take minutes instead of ~1min).
        shutil.rmtree(public_dir, ignore_errors=True)
