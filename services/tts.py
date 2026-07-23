"""ElevenLabs narration.

Calls the API once PER SEGMENT (the question, the key-phrase callout, each
solution step, ...) rather than once for the whole script. Segment start
times then fall out for free from concatenated clip durations.
"""

import os
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from elevenlabs.types import VoiceSettings

load_dotenv()

DEFAULT_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID") or "3AMU7jXQuQa3oRvRqUmb"  # "Viraj" (Hindi, narration)
MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

# language_code="hi" keeps the delivery committed to Hindi/Indian-English
# phonetics throughout a code-mixed Hinglish sentence, rather than switching
# to a generic/American accent whenever it hits an English technical term.
LANGUAGE_CODE = "hi"

# Calm, medium-paced, faculty-explaining-a-question delivery: speed slightly
# under 1.0 (ElevenLabs' natural pace reads a bit fast for a teaching video),
# high stability and low style so the tone stays even rather than expressive/
# excited, matching a calm classroom voice rather than an ad-read.
VOICE_SETTINGS = VoiceSettings(stability=0.65, similarity_boost=0.8, style=0.15, speed=0.92)

# A curated list of ElevenLabs' stable premade voices, not a live API lookup:
# the project's API key only has text-to-speech permission (no voices_read),
# so GET /v1/voices 401s even though synthesis with any of these IDs works
# fine. Update this list by hand if the team wants more options.
VOICES = [
    {"voice_id": "3AMU7jXQuQa3oRvRqUmb", "name": "Viraj (Hindi, male, narration) — default"},
    {"voice_id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel (female, calm)"},
    {"voice_id": "pNInz6obpgDQGcFmaJgB", "name": "Adam (male, deep)"},
    {"voice_id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella (female, soft)"},
    {"voice_id": "ErXwobaYiN019PkySvjV", "name": "Antoni (male, warm)"},
    {"voice_id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi (female, strong)"},
]


def list_voices() -> list[dict]:
    return VOICES


def _client() -> ElevenLabs:
    key = os.getenv("ELEVENLABS_API_KEY", "")
    if not key or key.startswith("your_"):
        raise RuntimeError("ELEVENLABS_API_KEY is not set in .env")
    return ElevenLabs(api_key=key)


def _wav_duration_seconds(path: str | Path) -> float:
    with wave.open(str(path), "rb") as f:
        return f.getnframes() / float(f.getframerate())


def narrate_segment(text: str, out_path: str | Path, voice_id: str = DEFAULT_VOICE_ID) -> dict:
    """Synthesize one narration segment. Returns {path, duration_s}."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    chunks = _client().text_to_speech.convert(
        voice_id=voice_id, text=text, model_id=MODEL_ID, output_format="wav_44100",
        voice_settings=VOICE_SETTINGS, language_code=LANGUAGE_CODE,
    )
    with out_path.open("wb") as f:
        for chunk in chunks:
            f.write(chunk)
    duration = _wav_duration_seconds(out_path)
    return {"path": str(out_path), "duration_s": duration}


def narrate_segments(segments: list[dict], out_dir: str | Path, voice_id: str = DEFAULT_VOICE_ID) -> list[dict]:
    """segments: [{id, text}, ...]. Returns the same list with narration info
    (path/duration_s/cue_start_s) merged in, and cue_start_s set from the
    running total of prior segment durations.

    Segments are independent ElevenLabs calls (see module docstring) so they
    fire concurrently — order only matters for computing cue_start_s
    afterward, not for issuing the requests, and this is the single biggest
    lever on wall-clock render time for questions with many solution steps.
    """
    out_dir = Path(out_dir)
    with ThreadPoolExecutor(max_workers=min(8, len(segments))) as pool:
        infos = list(pool.map(
            lambda seg: narrate_segment(seg["text"], out_dir / f"{seg['id']}.wav", voice_id=voice_id),
            segments,
        ))

    results = []
    cue_start = 0.0
    for seg, info in zip(segments, infos):
        results.append({**seg, **info, "cue_start_s": cue_start})
        cue_start += info["duration_s"]
    return results
