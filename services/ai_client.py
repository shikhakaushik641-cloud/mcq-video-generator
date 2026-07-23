"""AI client for the MCQ Video Generator.

Backend selection is automatic:
- Anthropic Claude when ANTHROPIC_API_KEY is configured (preferred)
- Azure OpenAI (AZURE_OPENAI_*) as fallback

Copied from flashcard-generator/services/ai_client.py to keep both PW tools
on the same LLM-call conventions.
"""

import base64
import json
import os
import re
import time
from typing import Any, Optional

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = os.getenv("MCQ_MODEL", "claude-sonnet-4-6")
MAX_RETRIES = 3
# Reasoning tokens count against the completion cap on gpt-5.x deployments;
# long prompts can burn >30k before the JSON finishes, so keep this high.
AZURE_MAX_TOKENS = 64000


def _anthropic_key() -> str:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    return "" if not key or key.startswith("your_") else key


def _azure_configured() -> bool:
    return bool(os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_KEY"))


def backend_name() -> str:
    if _anthropic_key():
        return "claude"
    if _azure_configured():
        return "azure"
    raise RuntimeError(
        "No AI backend configured: set ANTHROPIC_API_KEY or AZURE_OPENAI_* in .env")


def _call_claude(prompt: str, system: str, max_tokens: int,
                 images: Optional[list[bytes]]) -> str:
    content: list[dict] = []
    for img in images or []:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png",
                       "data": base64.b64encode(img).decode()},
        })
    content.append({"type": "text", "text": prompt})
    client = anthropic.Anthropic(api_key=_anthropic_key())
    msg = client.messages.create(
        model=MODEL, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": content}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")


def _call_azure(prompt: str, system: str, max_tokens: int,
                images: Optional[list[bytes]]) -> str:
    from openai import AzureOpenAI

    client = AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
        api_key=os.getenv("AZURE_OPENAI_KEY", ""),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
    )
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.2-ngmc")
    content: list[dict] = []
    for img in images or []:
        content.append({
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,"
                          + base64.b64encode(img).decode()},
        })
    content.append({"type": "text", "text": f"[System instruction: {system}]\n\n{prompt}"})
    resp = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": content}],
        max_completion_tokens=max(max_tokens, AZURE_MAX_TOKENS),
    )
    return resp.choices[0].message.content or ""


def call_ai(prompt: str, system: str = "", max_tokens: int = 8000,
            images: Optional[list[bytes]] = None) -> str:
    """Text (optionally multimodal) completion with retries."""
    system = system or "You are an expert educational content designer."
    backend = backend_name()
    last_err: Exception = RuntimeError("unreachable")
    for attempt in range(MAX_RETRIES):
        try:
            if backend == "claude":
                return _call_claude(prompt, system, max_tokens, images)
            return _call_azure(prompt, system, max_tokens, images)
        except Exception as e:
            last_err = e
            status = getattr(e, "status_code", None)
            if status is not None and status < 500 and status != 429:
                raise
            time.sleep(2 * (attempt + 1))
    raise last_err


def _loads_lenient(candidate: str) -> Any:
    """json.loads with progressively aggressive repairs."""
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(candidate, strict=False)
    except json.JSONDecodeError:
        pass
    repaired = candidate
    repaired = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", repaired)   # invalid escapes
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)            # trailing commas
    # stray ** emphasis markers OUTSIDE strings, e.g.  **"**text**",
    repaired = re.sub(r'([\[,:{]\s*)\*\*+(?=")', r"\1", repaired)
    repaired = re.sub(r'(")\*\*+(\s*[,\]\}:])', r"\1\2", repaired)
    return json.loads(repaired, strict=False)


def _salvage_truncated(text: str, start_char: str, end_char: str) -> Any:
    """Best-effort recovery of a truncated JSON object/array."""
    for cut in range(len(text) - 1, 0, -1):
        if text[cut] not in ("}", "]"):
            continue
        candidate = text[: cut + 1]
        opens = candidate.count("{") - candidate.count("}")
        obrk = candidate.count("[") - candidate.count("]")
        if opens < 0 or obrk < 0:
            continue
        fixed = re.sub(r",\s*$", "", candidate) + "]" * obrk + "}" * opens
        try:
            return _loads_lenient(fixed)
        except json.JSONDecodeError:
            continue
    return None


def extract_json(raw: str) -> Any:
    """Pull the first complete JSON object or array from model output."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()
    try:
        return _loads_lenient(raw)
    except json.JSONDecodeError:
        pass
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = raw.find(start_char)
        if start == -1:
            continue
        depth = 0
        in_str = False
        escape = False
        for i, ch in enumerate(raw[start:], start):
            if escape:
                escape = False
                continue
            if ch == "\\" and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    return _loads_lenient(raw[start : i + 1])
        salvaged = _salvage_truncated(raw[start:], start_char, end_char)
        if salvaged is not None:
            return salvaged
    raise ValueError(f"No JSON found in model output: {raw[:300]}")


def _save_debug(raw: str) -> None:
    try:
        debug_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "jobs")
        os.makedirs(debug_dir, exist_ok=True)
        with open(os.path.join(debug_dir, "_last_ai_raw.txt"), "w",
                  encoding="utf-8") as f:
            f.write(raw)
    except OSError:
        pass


def call_ai_json(prompt: str, system: str = "", max_tokens: int = 8000,
                 images: Optional[list[bytes]] = None) -> Any:
    """Completion that must return JSON; retries once on parse failure."""
    raw = call_ai(prompt, system=system, max_tokens=max_tokens, images=images)
    _save_debug(raw)
    try:
        return extract_json(raw)
    except (ValueError, json.JSONDecodeError):
        retry_prompt = (prompt + "\n\nIMPORTANT: Your previous answer was not valid "
                        "JSON. Respond with ONLY the JSON, no prose, no markdown fences.")
        raw = call_ai(retry_prompt, system=system, max_tokens=max_tokens, images=images)
        _save_debug(raw)
        return extract_json(raw)
