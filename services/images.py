"""Diagram extraction from question-bank source PDFs.

Extract each figure's embedded raster XObject DIRECTLY (not a page-region crop).
This is watermark-free and tight by construction: the page's watermark/background
are separate overlay objects (never part of a figure raster); captions, external
vector labels and body text live on the page, not inside the raster, so they are
excluded automatically; labels baked INTO the illustration are preserved.

Copied from flashcard-generator/services/images.py — same underlying operation
(pull clean diagram rasters out of a source PDF), just consumed here per-question
instead of per-flashcard.
"""

import hashlib
import io
from collections import Counter
from pathlib import Path

import fitz
from PIL import Image

RECUR_PAGES = 3          # a size/xref on >= this many pages is decorative
MIN_PIXELS = 150         # raster must be at least this wide & tall (source px)
MIN_PLACED_PT = 70.0     # and occupy at least this much on the page (points)
MAX_ASPECT = 6.0         # drop thin strips/rules
MAX_DIM = 1100           # downscale huge rasters
SKIP_PAGES: set[int] = set()
MAX_PER_PAGE = 3
BLANK_STD = 6.0          # skip near-uniform (blank) images


def _decorative(doc: fitz.Document) -> tuple[set[int], set[tuple[int, int]]]:
    xref_pages: dict[int, int] = {}
    size_pages: Counter = Counter()
    for page in doc:
        xrefs, sizes = set(), set()
        for info in page.get_image_info(xrefs=True):
            xrefs.add(info.get("xref", 0))
            sizes.add((info.get("width", 0), info.get("height", 0)))
        xrefs.discard(0)
        for x in xrefs:
            xref_pages[x] = xref_pages.get(x, 0) + 1
        for s in sizes:
            size_pages[s] += 1
    dec_xrefs = {x for x, n in xref_pages.items() if n >= RECUR_PAGES}
    dec_sizes = {s for s, n in size_pages.items() if n >= RECUR_PAGES}
    return dec_xrefs, dec_sizes


def _is_blank(png_bytes: bytes) -> bool:
    try:
        im = Image.open(io.BytesIO(png_bytes)).convert("L")
        im.thumbnail((64, 64))
        px = list(im.getdata())
        mean = sum(px) / len(px)
        var = sum((p - mean) ** 2 for p in px) / len(px)
        return var ** 0.5 < BLANK_STD
    except Exception:
        return False


def _is_decorative_lineart(png_bytes: bytes) -> bool:
    """True for brand line-art (e.g. a red mascot sketch on white): mostly white
    with saturated strokes concentrated in a single hue. Keeps gray line diagrams
    (microscope) and multi-colour illustrations (cells)."""
    try:
        im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        im.thumbnail((80, 80))
        hsv = im.convert("HSV")
        pix = list(hsv.getdata())
        rgb = list(im.getdata())
        total = len(pix)
        white = sum(1 for r, g, b in rgb if r > 235 and g > 235 and b > 235)
        white_frac = white / total
        nonwhite = [(h, s, v) for (h, s, v), (r, g, b) in zip(pix, rgb)
                    if not (r > 235 and g > 235 and b > 235)]
        if not nonwhite:
            return False
        sat = [h for h, s, v in nonwhite if s > 60 and v > 40]
        sat_frac = len(sat) / len(nonwhite)
        if not sat:
            return False
        bins = [0] * 12
        for h in sat:
            bins[(h * 12) // 256] += 1
        hue_conc = max(bins) / len(sat)
        return white_frac > 0.78 and sat_frac > 0.5 and hue_conc > 0.65
    except Exception:
        return False


def _normalise(raw: bytes, ext: str) -> bytes:
    """Re-encode to PNG on a white background, downscaled if huge."""
    im = Image.open(io.BytesIO(raw))
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im).convert("RGB")
    else:
        im = im.convert("RGB")
    if max(im.size) > MAX_DIM:
        im.thumbnail((MAX_DIM, MAX_DIM))
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def extract_diagrams(pdf_path: str | Path, out_dir: str | Path) -> dict[int, list[str]]:
    """Return {page_number(1-based): [png_path, ...]} of clean figure rasters."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    try:
        dec_xrefs, dec_sizes = _decorative(doc)
        by_page: dict[int, list[str]] = {}
        hashes: set[str] = set()

        for pno, page in enumerate(doc, 1):
            if pno in SKIP_PAGES:
                continue
            cands = []
            for info in page.get_image_info(xrefs=True):
                xref = info.get("xref", 0)
                w, h = info.get("width", 0), info.get("height", 0)
                if xref in dec_xrefs or (w, h) in dec_sizes:
                    continue
                if w < MIN_PIXELS or h < MIN_PIXELS:
                    continue
                if max(w, h) / max(min(w, h), 1) > MAX_ASPECT:
                    continue
                bbox = fitz.Rect(info["bbox"])
                if bbox.width < MIN_PLACED_PT or bbox.height < MIN_PLACED_PT:
                    continue
                cands.append((bbox.width * bbox.height, xref, w, h))
            cands.sort(reverse=True)

            kept = 0
            for _, xref, w, h in cands:
                if kept >= MAX_PER_PAGE:
                    break
                try:
                    img = doc.extract_image(xref)
                except Exception:
                    continue
                try:
                    data = _normalise(img["image"], img.get("ext", "png"))
                except Exception:
                    continue
                if _is_blank(data) or _is_decorative_lineart(data):
                    continue
                digest = hashlib.md5(data).hexdigest()
                if digest in hashes:
                    continue
                hashes.add(digest)
                path = out_dir / f"diagram_p{pno:02d}_{kept}.png"
                path.write_bytes(data)
                by_page.setdefault(pno, []).append(str(path))
                kept += 1
        return by_page
    finally:
        doc.close()
