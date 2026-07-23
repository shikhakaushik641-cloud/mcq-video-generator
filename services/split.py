"""Split a question bank's raw extracted text into per-question blocks.

Best-effort on purpose: a bad split just produces one bad job that gets
caught at that question's own review step (services/structure.py already
assumes its input may be noisy) — there's no silent-failure path here, so
a simple heuristic is the right amount of engineering for this step.
"""

import re

_QUESTION_START = re.compile(
    r"(?m)^\s*(?:Q\.?\s*\d+\.?|Question\s+\d+\.?|\d+[.)]\s+)",
)
_PAGE_MARKER = re.compile(r"\[Page (\d+)\]")

MIN_CHUNK_CHARS = 40  # drop stray fragments before the first real question


def _page_of(text: str, pos: int) -> int | None:
    """Last [Page N] marker at or before `pos`, if the text has any."""
    last = None
    for m in _PAGE_MARKER.finditer(text, 0, pos + 1):
        last = int(m.group(1))
    return last


def split_questions(text: str) -> list[dict]:
    """Return [{text, page}, ...] — one entry per detected question. `page`
    is None when the source has no [Page N] markers (e.g. docx)."""
    starts = [m.start() for m in _QUESTION_START.finditer(text)]
    if not starts:
        stripped = text.strip()
        return [{"text": stripped, "page": None}] if stripped else []

    chunks = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        chunk = text[start:end].strip()
        if len(chunk) < MIN_CHUNK_CHARS:
            continue
        chunks.append({"text": chunk, "page": _page_of(text, start)})
    return chunks
