"""
lens_ai.py - AI brain for Lens.

Uses Groq's OpenAI-compatible API with Llama 3.2 Vision (90B) by default.
Free to run on Groq's generous tier.

Single-image strategy: Llama vision models accept one image per request,
so we send a composed frame-grid image (built in lens_video.py) plus the
transcript text. This works for one or multiple videos by stacking grids.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable, Optional

from groq import Groq

from lens_video import VideoData
from prompts import Preset, context_block, calibration_block


# Groq model ids change occasionally. Pick the strongest vision-capable model
# on the platform and fall back if it's been retired. Updated as of late 2025.
DEFAULT_MODEL = "meta-llama/llama-4-maverick-17b-128e-instruct"
FALLBACK_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.2-90b-vision-preview",
    "llama-3.2-11b-vision-preview",
]
DEFAULT_MAX_TOKENS = 4096


@dataclass
class ChatTurn:
    role: str  # "user" | "assistant" | "system"
    content: list[dict] = field(default_factory=list)  # OpenAI-format content


def make_client(api_key: Optional[str] = None) -> Groq:
    key = api_key or os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Paste it into the sidebar, set the "
            "GROQ_API_KEY environment variable, or add it to Streamlit secrets."
        )
    return Groq(api_key=key)


# ---------------------- content block builders ----------------------------

def _video_text_block(video: VideoData, label: str) -> str:
    return (
        f"=== {label}: {video.title} ===\n"
        f"Source: {video.source}\n"
        f"Duration: {_clock(video.duration)}\n"
        f"Transcript source: {video.transcript_source}\n\n"
        f"--- TRANSCRIPT ({label}) ---\n"
        f"{video.transcript_text() or '(no transcript available)'}\n"
        f"--- FRAME GRID ({label}) ---\n"
        f"The image below is a grid of {len(video.frames)} frames pulled from this "
        f"video. Each tile shows one frame with its timestamp burned onto the top-left. "
        f"Read the grid like a comic strip - left to right, top to bottom in chronological "
        f"order. Always cite timestamps from the labels when you reference a moment.\n"
    )


def build_initial_turn(
    *,
    videos: list[VideoData],
    preset: Preset,
    user_goal: str = "",
) -> ChatTurn:
    """Build the first user turn: all videos (text + grid images) + starter prompt.

    OpenAI-compatible content blocks: text and image_url. We attach one
    image_url per video (the composed grid).
    """
    content: list[dict] = []

    for i, v in enumerate(videos, start=1):
        label = f"Video {i}" if len(videos) > 1 else "Video"
        content.append({"type": "text", "text": _video_text_block(v, label)})
        grid_b64 = v.frame_grid_base64()
        if grid_b64:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{grid_b64}",
                },
            })

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
    client: Groq,
    preset: Preset,
    my_context: str,
    history: list[ChatTurn],
    target_kpis: str = "",
    reference_notes: str = "",
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> Iterable[str]:
    """Stream tokens for the next assistant reply.

    Tries DEFAULT_MODEL first; on model-not-found errors, falls back through
    FALLBACK_MODELS so the app keeps working as Groq's catalog rotates.
    """
    system = (preset.system_prompt
              + context_block(my_context)
              + calibration_block(target_kpis, reference_notes))

    messages = [{"role": "system", "content": system}]
    for t in history:
        # Anthropic uses content blocks for both roles; OpenAI/Groq use a string
        # for assistant role and a list for multi-modal user content.
        if t.role == "assistant":
            text = "".join(b.get("text", "") for b in t.content if b.get("type") == "text")
            messages.append({"role": "assistant", "content": text})
        else:
            messages.append({"role": "user", "content": t.content})

    candidates = [model] + [m for m in FALLBACK_MODELS if m != model]
    last_error: Optional[Exception] = None

    for candidate in candidates:
        try:
            stream = client.chat.completions.create(
                model=candidate,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.6,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield delta.content
            return
        except Exception as e:
            last_error = e
            msg = str(e).lower()
            # Only fall back on "model not found" / decommissioned / unsupported errors.
            if not any(s in msg for s in ("model", "not found", "decommissioned",
                                          "deprecated", "does not exist", "unsupported")):
                raise
            continue

    if last_error:
        raise last_error


# ---------------------- helpers -------------------------------------------

def _clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"
