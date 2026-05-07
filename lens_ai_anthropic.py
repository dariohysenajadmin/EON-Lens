"""
lens_ai_anthropic.py - Anthropic Claude provider for Lens.

Parallel to lens_ai.py (Groq+Llama) but uses Anthropic's API directly.

Key difference: Claude handles many images natively (up to 100 per request),
so instead of composing a single frame-grid image we send each frame as its
own image block with its timestamp in the surrounding text. This gives the
model much sharper temporal grounding for Marketing Hook Teardown and
similar timestamp-sensitive analyses.

Public API matches lens_ai.py so app.py can swap providers with one import.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable, Optional

import anthropic

from lens_video import VideoData
from prompts import Preset, context_block, calibration_block


# Claude model IDs - update as Anthropic releases new ones.
DEFAULT_MODEL = "claude-sonnet-4-6"
FALLBACK_MODELS = [
    "claude-opus-4-6",
    "claude-haiku-4-5-20251001",
]
DEFAULT_MAX_TOKENS = 4096

# Cap per-video frame uploads. Claude handles many images natively, but on
# small-RAM hosts (e.g. Render free tier at 512MB) holding 20+ base64-encoded
# JPEGs in memory while building the request can push the container into OOM.
# 12 frames still gives strong temporal coverage of any video under ~10 min.
MAX_FRAMES_PER_VIDEO = 12


@dataclass
class ChatTurn:
    role: str  # "user" | "assistant"
    content: list[dict] = field(default_factory=list)  # Anthropic content blocks


def make_client(api_key: Optional[str] = None) -> anthropic.Anthropic:
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Paste it into the sidebar, set the "
            "ANTHROPIC_API_KEY environment variable, or add it to Streamlit secrets."
        )
    return anthropic.Anthropic(api_key=key)


# ---------------------- content block builders ----------------------------

def _video_header_block(video: VideoData, label: str) -> dict:
    return {
        "type": "text",
        "text": (
            f"=== {label}: {video.title} ===\n"
            f"Source: {video.source}\n"
            f"Duration: {_clock(video.duration)}\n"
            f"Transcript source: {video.transcript_source}\n\n"
            f"--- TRANSCRIPT ({label}) ---\n"
            f"{video.transcript_text() or '(no transcript available)'}\n"
            f"--- FRAMES ({label}) ---\n"
            f"Below are {min(len(video.frames), MAX_FRAMES_PER_VIDEO)} frames "
            f"sampled across the video, each labeled with its timestamp. "
            f"Cite timestamps when you reference a moment."
        ),
    }


def _frame_blocks(video: VideoData) -> list[dict]:
    """Emit one image block per frame, each preceded by a timestamp text block."""
    blocks: list[dict] = []
    frames = video.frames[:MAX_FRAMES_PER_VIDEO]
    for f in frames:
        blocks.append({"type": "text", "text": f"[frame at {f.clock()}]"})
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": f.base64_jpeg,
            },
        })
    return blocks


def build_initial_turn(
    *,
    videos: list[VideoData],
    preset: Preset,
    user_goal: str = "",
) -> ChatTurn:
    content: list[dict] = []

    for i, v in enumerate(videos, start=1):
        label = f"Video {i}" if len(videos) > 1 else "Video"
        content.append(_video_header_block(v, label))
        content.extend(_frame_blocks(v))

    starter = preset.starter_prompt
    if user_goal.strip():
        starter += f"\n\nThe user's specific goal for this analysis:\n{user_goal.strip()}"
    content.append({"type": "text", "text": starter})

    return ChatTurn(role="user", content=content)


def build_followup_turn(text: str) -> ChatTurn:
    return ChatTurn(role="user", content=[{"type": "text", "text": text}])


def build_remix_turn(preset: Preset) -> ChatTurn:
    return ChatTurn(
        role="user",
        content=[{"type": "text", "text": preset.remix_prompt}],
    )


def build_assistant_turn(text: str) -> ChatTurn:
    return ChatTurn(role="assistant", content=[{"type": "text", "text": text}])


# ---------------------- streaming inference -------------------------------

def stream_response(
    *,
    client: anthropic.Anthropic,
    preset: Preset,
    my_context: str,
    history: list[ChatTurn],
    target_kpis: str = "",
    reference_notes: str = "",
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> Iterable[str]:
    """Stream tokens for the next assistant reply via Anthropic's Messages API."""
    system = (preset.system_prompt
              + context_block(my_context)
              + calibration_block(target_kpis, reference_notes))

    messages = []
    for t in history:
        # Anthropic accepts the same content-block format for both roles.
        # Assistant turns store as plain text; convert back to a single text block.
        if t.role == "assistant":
            text = "".join(b.get("text", "") for b in t.content if b.get("type") == "text")
            messages.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
        else:
            messages.append({"role": "user", "content": t.content})

    candidates = [model] + [m for m in FALLBACK_MODELS if m != model]
    last_error: Optional[Exception] = None

    for candidate in candidates:
        try:
            with client.messages.stream(
                model=candidate,
                system=system,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.6,
            ) as stream:
                for chunk in stream.text_stream:
                    if chunk:
                        yield chunk
            return
        except Exception as e:
            last_error = e
            msg = str(e).lower()
            if not any(s in msg for s in ("model", "not_found", "not found",
                                           "deprecated", "does not exist", "unsupported")):
                raise
            continue

    if last_error:
        raise last_error


# ---------------------- helpers -------------------------------------------

def _clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"
