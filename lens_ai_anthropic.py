"""
lens_ai_anthropic.py - Anthropic Claude provider for Lens.

Parallel to lens_ai.py (Groq+Llama) but uses Anthropic's API directly.

Key difference: Claude handles many images natively (up to 100 per request),
so instead of composing a single frame-grid image we send each frame as its
own image block with its timestamp in the surrounding text. This gives the
model much sharper temporal grounding for Marketing Hook Teardown and
similar timestamp-sensitive analyses.

Public API matches lens_ai.py so app.py can swap providers with one import.

Resilience notes (2026-06 patch):
  * Streaming requests are retried with backoff on transient connection
    errors (Render's free-tier load balancer drops idle TCP connections
    aggressively and Anthropic's edge has occasional blips).
  * If streaming retries are exhausted on a given model, we automatically
    fall back to a non-streaming request on the same model. Some hosts
    break long-lived HTTP streams while normal request/response calls
    keep working.
  * Only after BOTH streaming retries and the non-streaming fallback fail
    do we move to the next candidate model.
  * Errors raised from this module include the model name and the
    underlying exception class so app.py can surface useful diagnostics.
"""

from __future__ import annotations
import os
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional

import anthropic
import httpx

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

# Generous read timeout: streaming responses on Render's free tier can take
# a while to start producing tokens, and we'd rather wait than abort early.
DEFAULT_TIMEOUT = httpx.Timeout(connect=15.0, read=180.0, write=60.0, pool=30.0)

# Retry tuning for streaming on transient errors.
MAX_STREAM_RETRIES = 2          # total streaming attempts = 1 + this
BACKOFF_BASE_SECONDS = 1.5      # delays: 1.5s, 3.0s

# Exception classes we'll treat as transient (retry-worthy).
_TRANSIENT_ERRORS: tuple = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
)
for _maybe in ("InternalServerError", "RateLimitError", "APIStatusError"):
    _cls = getattr(anthropic, _maybe, None)
    if _cls is not None:
        _TRANSIENT_ERRORS = _TRANSIENT_ERRORS + (_cls,)

# Substrings in error messages that mean "this model is not available;
# try the next one in the fallback list" (rather than retrying the same one).
_FALLBACK_TRIGGERS = (
    "model", "not_found", "not found", "deprecated", "does not exist",
    "unsupported", "invalid_request_error",
)


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
    return anthropic.Anthropic(api_key=key, timeout=DEFAULT_TIMEOUT, max_retries=0)


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

def _build_messages(history: list[ChatTurn]) -> list[dict]:
    messages: list[dict] = []
    for t in history:
        # Anthropic accepts the same content-block format for both roles.
        # Assistant turns store as plain text; convert back to a single text block.
        if t.role == "assistant":
            text = "".join(b.get("text", "") for b in t.content if b.get("type") == "text")
            messages.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
        else:
            messages.append({"role": "user", "content": t.content})
    return messages


def _looks_like_model_problem(exc: Exception) -> bool:
    """True if the error message suggests we should try the next model."""
    msg = str(exc).lower()
    return any(s in msg for s in _FALLBACK_TRIGGERS)


def _wrap_fatal(exc: Exception, model: str) -> RuntimeError:
    """Turn a low-level error into one that names the model + exception class
    so app.py can show something more useful than 'Connection error.'"""
    return RuntimeError(
        f"Anthropic {type(exc).__name__} on model {model}: {exc}"
    )


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
    """Yield assistant tokens.

    Order of attempts per model:
      1. Streaming, retried up to MAX_STREAM_RETRIES times on transient
         errors (but only if no tokens have been yielded yet — once the
         user has seen output, retrying would duplicate it).
      2. Non-streaming request as a final attempt on the same model.
      3. Next model in the candidates list.

    If everything fails, raise a RuntimeError that names the last model
    tried and the underlying exception class.
    """
    system = (preset.system_prompt
              + context_block(my_context)
              + calibration_block(target_kpis, reference_notes))
    messages = _build_messages(history)

    candidates = [model] + [m for m in FALLBACK_MODELS if m != model]
    last_error: Optional[Exception] = None
    last_model: Optional[str] = None

    for candidate in candidates:
        last_model = candidate

        # --- 1. Streaming with retries ---
        streaming_done = False
        for attempt in range(MAX_STREAM_RETRIES + 1):
            yielded_any = False
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
                            yielded_any = True
                            yield chunk
                if yielded_any:
                    return
                # Stream opened cleanly but produced zero tokens — treat as
                # a transient connection problem and retry.
                last_error = RuntimeError(
                    f"Stream from {candidate} closed before any tokens arrived."
                )
            except _TRANSIENT_ERRORS as e:
                last_error = e
                if yielded_any:
                    # Cannot safely retry once we've already streamed tokens
                    # to the UI — that would duplicate output.
                    raise _wrap_fatal(e, candidate) from e
            except Exception as e:
                last_error = e
                if _looks_like_model_problem(e):
                    # Skip retries on this model — move on to the next one.
                    streaming_done = True
                    break
                # Auth / billing / validation errors are fatal.
                raise _wrap_fatal(e, candidate) from e

            # Backoff before next streaming attempt.
            if attempt < MAX_STREAM_RETRIES:
                time.sleep(BACKOFF_BASE_SECONDS * (attempt + 1))

        if streaming_done:
            # Bail to the next candidate model without trying non-streaming.
            continue

        # --- 2. Non-streaming fallback on the same model ---
        # Some hosts (Render free tier among them) break long-lived HTTP
        # streams while plain request/response calls go through fine.
        try:
            msg = client.messages.create(
                model=candidate,
                system=system,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.6,
            )
            text = "".join(
                getattr(b, "text", "")
                for b in msg.content
                if getattr(b, "type", "") == "text"
            )
            if text:
                yield text
                return
            last_error = RuntimeError(
                f"Non-streaming response from {candidate} contained no text."
            )
        except _TRANSIENT_ERRORS as e:
            last_error = e
        except Exception as e:
            last_error = e
            if not _looks_like_model_problem(e):
                raise _wrap_fatal(e, candidate) from e
        # Try the next candidate model.

    # --- All models exhausted ---
    err_name = type(last_error).__name__ if last_error else "Unknown"
    raise RuntimeError(
        f"All Anthropic models failed (last tried: {last_model}). "
        f"{err_name}: {last_error}"
    ) from last_error


# ---------------------- helpers -------------------------------------------

def _clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"
