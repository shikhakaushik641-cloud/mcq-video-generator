"""Bridge from a structured question JSON to a rendered mp4.

Builds the narration segments + circuit diagram stages, then drives the
custom Playwright frame-capture + ffmpeg encode/mux pipeline (see
services/frame_capture.py and services/video_encode.py) — this replaced a
Remotion subprocess call, which needed a paid company license PW isn't
under the free tier for; Playwright and ffmpeg have no such restriction.
"""

import json
import os
import shutil
from pathlib import Path
from typing import Callable

from services import frame_capture, video_encode
from services.diagrams import render_circuit_stages, render_molecule
from services.tts import DEFAULT_VOICE_ID, narrate_segments

RENDER_DIR = Path(__file__).parent.parent / "render"
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


def _file_url(path: str | Path) -> str:
    return Path(path).resolve().as_uri()


def _audio_ref(narrated: dict) -> dict:
    # "path" is unused by the visual composition now (audio is muxed by
    # ffmpeg, not played by the browser) — kept for debugging/inspection.
    return {"path": narrated["path"], "durationS": narrated["duration_s"]}


def build_props(question: dict, job_dir: str | Path, voice_id: str = DEFAULT_VOICE_ID,
                source_images: list[bytes] | None = None) -> tuple[dict, list[str]]:
    """Returns (props, ordered_audio_paths) — ordered_audio_paths is every
    segment's wav file in the exact order they're narrated (intro, question,
    concept?, diagram?, step0, step1, ...), for gapless concatenation later:
    the video's own cumulative frame timing is built from summing these
    same durations in this same order, so audio and video timelines match
    by construction as long as the concat order matches this one."""
    job_dir = Path(job_dir)
    audio_dir = job_dir / "audio"
    diagram_dir = job_dir / "diagrams"

    narration = _build_narration_segments(question)
    narrated = {n["id"]: n for n in narrate_segments(narration, audio_dir, voice_id=voice_id)}
    ordered_audio_paths = [narrated[seg["id"]]["path"] for seg in narration]

    diagram = question.get("diagram") or {"type": "none"}
    diagram_images: list[str] = []
    if diagram.get("type") == "circuit":
        diagram_images = render_circuit_stages(diagram["spec"], diagram_dir)
    elif diagram.get("type") == "molecule":
        diagram_images = [render_molecule(diagram["spec"], diagram_dir)]
    elif diagram.get("type") == "image" and source_images:
        diagram_dir.mkdir(parents=True, exist_ok=True)
        src_path = diagram_dir / "figure.png"
        src_path.write_bytes(source_images[0])
        diagram_images = [str(src_path)]

    panel = []
    if question.get("concept"):
        panel.append({"type": "concept", "note": question["concept"].get("note"), "audio": _audio_ref(narrated["concept"])})
    if diagram.get("type") != "none" and diagram_images:
        panel.append({
            "type": "diagram",
            "images": [_file_url(p) for p in diagram_images],
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

    props = {
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
    return props, ordered_audio_paths


def render_video(question: dict, job_dir: str | Path, out_name: str = "video.mp4",
                 voice_id: str = DEFAULT_VOICE_ID, source_images: list[bytes] | None = None,
                 on_progress: Callable[[str], None] | None = None) -> str:
    """on_progress, if given, is called with a human-readable string at each
    ~10% frame-capture milestone plus the encode/mux phase transitions — a
    long multi-step question can take many minutes (proportional to its own
    narration length, not something a code fix shrinks), so surfacing real
    progress matters more than the total number: it's the difference
    between "still working" and "looks frozen"."""
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    props, audio_paths = build_props(question, job_dir, voice_id=voice_id, source_images=source_images)
    props_path = job_dir / "props.json"
    props_path.write_text(json.dumps(props, indent=2, ensure_ascii=False), encoding="utf-8")

    frames_dir = job_dir / "frames"
    silent_video = job_dir / "_silent.mp4"
    combined_audio = job_dir / "_combined_audio.wav"
    out_path = job_dir / out_name

    last_reported_pct = -10

    def throttled_progress(done: int, total: int) -> None:
        nonlocal last_reported_pct
        pct = (done * 100 // total) if total else 0
        if pct >= last_reported_pct + 10:
            last_reported_pct = pct - (pct % 10)
            if on_progress:
                on_progress(f"Rendering video… {pct}% ({done}/{total} frames)")

    try:
        concurrency = max(1, (os.cpu_count() or 4) - 2)
        frame_capture.capture_all(props, frames_dir, concurrency, on_progress=throttled_progress)

        if on_progress:
            on_progress("Encoding captured frames…")
        video_encode.encode_frames_to_video(frames_dir, silent_video, fps=props["fps"])

        if on_progress:
            on_progress("Mixing narration audio…")
        video_encode.concat_audio(audio_paths, combined_audio)
        video_encode.mux(silent_video, combined_audio, out_path)
        return str(out_path)
    finally:
        # Per-job scratch state — a long question can leave several thousand
        # JPEGs behind otherwise.
        shutil.rmtree(frames_dir, ignore_errors=True)
        silent_video.unlink(missing_ok=True)
        combined_audio.unlink(missing_ok=True)
