"""ffmpeg-based encoding: JPEG frame sequence -> silent mp4, WAV segment
concatenation -> combined audio track, then mux into the final mp4.

Uses imageio-ffmpeg's bundled binary (properly libx264/aac-capable) via
subprocess — invoking a prebuilt ffmpeg binary this way is standard "mere
aggregation," not the same restriction category as a per-seat commercial
license (this whole module exists to get off of one of those).
"""

import subprocess
import wave
from pathlib import Path

import imageio_ffmpeg


def _ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg command failed: {' '.join(cmd)}\n{result.stderr[-2000:]}")


def encode_frames_to_video(frames_dir: str | Path, out_path: str | Path, fps: int) -> None:
    frames_dir = Path(frames_dir)
    cmd = [
        _ffmpeg(), "-y", "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%06d.jpg"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    _run(cmd)


def _wav_params(path: Path) -> tuple[int, int, int]:
    with wave.open(str(path), "rb") as f:
        return (f.getframerate(), f.getnchannels(), f.getsampwidth())


def concat_audio(segment_paths: list[str | Path], out_path: str | Path) -> None:
    """Joins WAV segments in the given order with ffmpeg's concat demuxer
    (`-c copy`, sample-accurate/gapless). Guards against a silent-drift bug
    by asserting every segment shares the same sample rate/channels/bit
    depth before concatenating — all segments come from the same ElevenLabs
    call site with a fixed output_format today, so this should never
    actually fire, but a future TTS param change should fail loudly here
    rather than let the audio slowly drift out of sync with the video."""
    paths = [Path(p) for p in segment_paths]
    if not paths:
        raise ValueError("no audio segments to concatenate")
    params = {p: _wav_params(p) for p in paths}
    distinct = set(params.values())
    if len(distinct) > 1:
        raise RuntimeError(f"audio segment format mismatch, cannot gaplessly concat: {params}")

    out_path = Path(out_path)
    filelist = out_path.with_suffix(".filelist.txt")
    filelist.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in paths),
        encoding="utf-8",
    )
    try:
        _run([_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(filelist),
             "-c", "copy", str(out_path)])
    finally:
        filelist.unlink(missing_ok=True)


def mux(video_path: str | Path, audio_path: str | Path, out_path: str | Path) -> None:
    cmd = [
        _ffmpeg(), "-y", "-i", str(video_path), "-i", str(audio_path),
        "-c:v", "copy", "-c:a", "aac", "-shortest", str(out_path),
    ]
    _run(cmd)
