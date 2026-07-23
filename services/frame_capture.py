"""Frame-by-frame capture of the video composition via Playwright.

Replaces Remotion's role of "screenshot the composition at every frame" —
the composition itself (render/src/MCQVideo.tsx, bundled by esbuild into
render/dist/bundle.js) is unchanged in spirit, just driven by an explicit
`frame` prop instead of Remotion's useCurrentFrame() hook. One browser
process, N contexts (matching the concurrency Remotion was already tuned
to use here), each capturing a contiguous frame range.
"""

import asyncio
import json
import math
from pathlib import Path
from typing import Callable

from playwright.async_api import async_playwright

RENDER_DIR = Path(__file__).parent.parent / "render"


def total_frames(props: dict) -> int:
    """Mirrors render/src/Root.tsx's old totalFrames() — sum of every
    segment's own duration converted to frames, each segment at least 1
    frame (matches secondsToFrames in MCQVideo.tsx)."""
    fps = props["fps"]

    def seconds_to_frames(s: float) -> int:
        return max(1, round(s * fps))

    frames = seconds_to_frames(props["intro"]["audio"]["durationS"])
    frames += seconds_to_frames(props["question"]["audio"]["durationS"])
    for item in props["panel"]:
        frames += seconds_to_frames(item["audio"]["durationS"])
    return frames


def _build_html(props: dict, out_path: Path) -> None:
    katex_css = (RENDER_DIR / "node_modules" / "katex" / "dist" / "katex.min.css").as_uri()
    bundle_js = (RENDER_DIR / "dist" / "bundle.js").as_uri()
    html = (
        "<!doctype html><html><head>"
        f'<link rel="stylesheet" href="{katex_css}">'
        "<style>body{margin:0;}</style>"
        "</head><body>"
        '<div id="root"></div>'
        f"<script>window.__PROPS__ = {json.dumps(props)};</script>"
        f'<script src="{bundle_js}"></script>'
        "</body></html>"
    )
    out_path.write_text(html, encoding="utf-8")


async def _capture_range(
    browser, html_url: str, start: int, end: int, frames_dir: Path,
    width: int, height: int, on_frame_done: Callable[[], None],
) -> None:
    context = await browser.new_context(viewport={"width": width, "height": height})
    page = await context.new_page()
    await page.goto(html_url)
    # Replaces Remotion's automatic delayRender()-based asset waiting: make
    # sure web fonts (KaTeX + the Lucida Handwriting annotation font) and
    # any <img> already in the tree (diagram assets) are actually ready
    # before the first screenshot, or early frames show FOUT/fallback glyphs.
    await page.evaluate("document.fonts.ready")
    await page.wait_for_function(
        "Array.from(document.images).every(img => img.complete && img.naturalWidth > 0)"
    )
    for i in range(start, end):
        await page.evaluate(f"window.renderFrame({i})")
        # React's commit is async relative to evaluate() resolving — wait a
        # rAF tick so we don't screenshot a stale paint.
        await page.evaluate("new Promise(r => requestAnimationFrame(r))")
        await page.screenshot(path=str(frames_dir / f"frame_{i:06d}.jpg"), type="jpeg", quality=80)
        on_frame_done()
    await context.close()


async def _capture_all_async(
    props: dict, frames: int, frames_dir: Path, concurrency: int,
    on_progress: Callable[[int, int], None] | None,
) -> None:
    frames_dir.mkdir(parents=True, exist_ok=True)
    html_path = frames_dir / "_composition.html"
    _build_html(props, html_path)
    html_url = html_path.resolve().as_uri()

    done = 0

    def on_frame_done() -> None:
        # Single-threaded asyncio event loop — no lock needed, this runs to
        # completion between any two awaits.
        nonlocal done
        done += 1
        if on_progress:
            on_progress(done, frames)

    n_workers = max(1, min(concurrency, frames))
    chunk = math.ceil(frames / n_workers)
    ranges = [
        (i * chunk, min((i + 1) * chunk, frames))
        for i in range(n_workers) if i * chunk < frames
    ]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            await asyncio.gather(*[
                _capture_range(browser, html_url, start, end, frames_dir,
                               props["width"], props["height"], on_frame_done)
                for start, end in ranges
            ])
        finally:
            await browser.close()


def capture_all(
    props: dict, frames_dir: str | Path, concurrency: int,
    on_progress: Callable[[int, int], None] | None = None,
) -> int:
    """Renders every frame of `props` to numbered JPEGs in `frames_dir`.
    Returns the total frame count."""
    frames = total_frames(props)
    asyncio.run(_capture_all_async(props, frames, Path(frames_dir), concurrency, on_progress))
    return frames
