"""
Lens - the video intelligence app.
Run with: streamlit run app.py
"""

from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path
from typing import Optional

import streamlit as st
from dotenv import load_dotenv

from lens_video import VideoData, extract_video_data
from lens_ai import (
    build_assistant_turn,
    build_followup_turn,
    build_initial_turn,
    build_remix_turn,
    make_client,
    stream_response,
)
from prompts import PRESETS, Preset
from theme import apply_theme


load_dotenv()

st.set_page_config(
    page_title="Lens",
    page_icon="L",
    layout="wide",
    initial_sidebar_state="expanded",
)

DEFAULTS = {
    "theme": "dark",
    "videos": [],
    "history": [],
    "display_log": [],
    "groq_key": os.environ.get("GROQ_API_KEY", ""),
    "my_context": "",
    "active_preset": None,
    "pending_custom_goal": False,
    "data_root": None,
}

try:
    if not DEFAULTS["groq_key"] and "GROQ_API_KEY" in st.secrets:
        DEFAULTS["groq_key"] = st.secrets["GROQ_API_KEY"]
except (FileNotFoundError, AttributeError):
    pass

for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)

if st.session_state.data_root is None:
    st.session_state.data_root = Path("data") / f"session-{uuid.uuid4().hex[:8]}"
    st.session_state.data_root.mkdir(parents=True, exist_ok=True)


st.markdown(apply_theme(st.session_state.theme), unsafe_allow_html=True)


URL_RE = re.compile(r"https?://\S+")


def _clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _frame_gallery_html(video, max_thumbs=8):
    pieces = []
    for f in video.frames[:max_thumbs]:
        pieces.append(f'<img src="data:image/jpeg;base64,{f.base64_jpeg}" alt="frame at {f.clock()}" />')
    extra = len(video.frames) - max_thumbs
    if extra > 0:
        pieces.append(f'<div style="align-self:center; color:var(--lens-muted); font-size:0.8rem">+{extra} more</div>')
    return f'<div class="lens-frames">{"".join(pieces)}</div>'


def _render_log_entry(entry):
    role = entry["role"]
    kind = entry["kind"]
    with st.chat_message(role):
        if kind == "video":
            v = entry["video"]
            st.markdown(f"**Loaded:** {v.title}")
            st.caption(f"{_clock(v.duration)} - {len(v.frames)} frames - {v.transcript_source.replace('_', ' ')}")
            st.markdown(_frame_gallery_html(v), unsafe_allow_html=True)
        elif kind == "text":
            st.markdown(entry["body"])
        elif kind == "error":
            st.error(entry["body"])
        elif kind == "info":
            st.info(entry["body"])


def _ensure_api_key():
    if not st.session_state.groq_key:
        st.session_state.display_log.append({
            "role": "assistant",
            "kind": "error",
            "body": "Add your Groq API key in the sidebar to start asking questions. Free at console.groq.com/keys.",
        })
        st.rerun()
        return False
    return True


def _process_video(source):
    placeholder = st.empty()
    def progress(msg):
        placeholder.info(msg)
    try:
        video = extract_video_data(source, max_frames=30, output_root=st.session_state.data_root, progress=progress)
        placeholder.empty()
        return video
    except Exception as e:
        placeholder.empty()
        st.session_state.display_log.append({"role": "assistant", "kind": "error", "body": f"Could not process video: {e}"})
        return None


def _run_preset(preset, user_goal=""):
    if not _ensure_api_key():
        return
    if not st.session_state.videos:
        st.session_state.display_log.append({
            "role": "assistant",
            "kind": "info",
            "body": "Drop a video URL or upload a file first, then I'll run the analysis.",
        })
        st.rerun()
        return

    initial = build_initial_turn(videos=st.session_state.videos, preset=preset, user_goal=user_goal)
    st.session_state.history = [initial]
    st.session_state.active_preset = preset.key

    starter_text = preset.starter_prompt
    if user_goal:
        starter_text += f"\n\n**Your goal:** {user_goal}"
    st.session_state.display_log.append({
        "role": "user",
        "kind": "text",
        "body": f"**[{preset.label}]**\n\n{starter_text}",
    })
    _stream_assistant_reply()


def _run_followup(text):
    if not _ensure_api_key():
        return
    if not st.session_state.history:
        if not st.session_state.videos:
            st.session_state.display_log.append({"role": "assistant", "kind": "info", "body": "Drop a video URL or upload a file first."})
            st.rerun()
            return
        _run_preset(PRESETS["custom_goal"], user_goal=text)
        return
    turn = build_followup_turn(text)
    st.session_state.history.append(turn)
    st.session_state.display_log.append({"role": "user", "kind": "text", "body": text})
    _stream_assistant_reply()


def _run_remix():
    if not _ensure_api_key():
        return
    if not st.session_state.active_preset:
        st.session_state.display_log.append({"role": "assistant", "kind": "info", "body": "Run an analysis first, then I'll remix it for your context."})
        st.rerun()
        return
    preset = PRESETS[st.session_state.active_preset]
    turn = build_remix_turn(preset)
    st.session_state.history.append(turn)
    st.session_state.display_log.append({"role": "user", "kind": "text", "body": "**[Remix for my context]**"})
    _stream_assistant_reply()


def _stream_assistant_reply():
    try:
        client = make_client(st.session_state.groq_key)
    except Exception as e:
        st.session_state.display_log.append({"role": "assistant", "kind": "error", "body": f"API key issue: {e}"})
        st.rerun()
        return

    preset = PRESETS.get(st.session_state.active_preset) or PRESETS["custom_goal"]

    for entry in st.session_state.display_log:
        _render_log_entry(entry)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        accumulated = ""
        try:
            for chunk in stream_response(
                client=client,
                preset=preset,
                my_context=st.session_state.my_context,
                history=st.session_state.history,
            ):
                accumulated += chunk
                placeholder.markdown(accumulated + " ")
            placeholder.markdown(accumulated)
        except Exception as e:
            placeholder.error(f"Streaming failed: {e}")
            return

    st.session_state.history.append(build_assistant_turn(accumulated))
    st.session_state.display_log.append({"role": "assistant", "kind": "text", "body": accumulated})


with st.sidebar:
    st.markdown('<div class="lens-brand"><span class="lens-dot"></span>Lens</div>', unsafe_allow_html=True)
    st.markdown('<div class="lens-tagline">Video intelligence for marketing & product teams.</div>', unsafe_allow_html=True)

    st.markdown("---")

    with st.expander("API key", expanded=not st.session_state.groq_key):
        st.session_state.groq_key = st.text_input(
            "Groq API key",
            value=st.session_state.groq_key,
            type="password",
            help="Required. Free at console.groq.com/keys.",
        )
        if st.session_state.groq_key:
            os.environ["GROQ_API_KEY"] = st.session_state.groq_key

    with st.expander("My Context", expanded=False):
        st.caption("Save your brand voice, audience, product, or tech stack. Lens uses this on every analysis and Remix.")
        st.session_state.my_context = st.text_area(
            "Context",
            value=st.session_state.my_context,
            height=200,
            placeholder=(
                "Marketing example:\n"
                "  - Brand: EON Reality, immersive XR for enterprise\n"
                "  - Audience: L&D leaders at Fortune 500\n"
                "  - Voice: confident, technical, never gimmicky\n\n"
                "Dev example:\n"
                "  - Stack: React + TypeScript, Tailwind, Next.js 14\n"
                "  - Style: functional components, react-query for data."
            ),
            label_visibility="collapsed",
        )

    st.markdown("### Videos in this session")
    if not st.session_state.videos:
        st.caption("No videos yet. Paste a URL or upload a file in the chat below.")
    else:
        for i, v in enumerate(st.session_state.videos, start=1):
            title_short = v.title[:60] + ('...' if len(v.title) > 60 else '')
            st.markdown(
                f'<div class="lens-video-card"><div class="title">Video {i}: {title_short}</div>'
                f'<div class="meta">{_clock(v.duration)} - {len(v.frames)} frames - {v.transcript_source.replace("_", " ")}</div></div>',
                unsafe_allow_html=True,
            )

    st.markdown("---")
    if st.button("Reset session", use_container_width=True):
        for k in ("videos", "history", "display_log", "active_preset", "pending_custom_goal"):
            st.session_state[k] = DEFAULTS[k]
        st.session_state.data_root = Path("data") / f"session-{uuid.uuid4().hex[:8]}"
        st.session_state.data_root.mkdir(parents=True, exist_ok=True)
        st.rerun()


st.markdown('<div class="lens-brand" style="font-size:2rem"><span class="lens-dot"></span>Lens</div>', unsafe_allow_html=True)
st.markdown('<div class="lens-tagline">Paste a video URL, upload a file, or ask a question.</div>', unsafe_allow_html=True)


st.markdown('<div class="lens-chip-row">', unsafe_allow_html=True)
chip_cols = st.columns(5)
chip_keys = ["marketing_hook", "product_demo", "custom_goal", "competitive_compare"]
for col, key in zip(chip_cols[:4], chip_keys):
    preset = PRESETS[key]
    if col.button(preset.label, key=f"chip_{key}", help=preset.short_blurb, use_container_width=True):
        if key == "custom_goal":
            st.session_state.pending_custom_goal = True
            st.rerun()
        else:
            _run_preset(preset)
            st.rerun()
with chip_cols[4]:
    if st.button("Remix for me", key="chip_remix", help="Reverse-engineer the analyzed video into something tuned for your brand or stack.", use_container_width=True, disabled=not st.session_state.active_preset):
        _run_remix()
        st.rerun()
st.markdown("</div>", unsafe_allow_html=True)


with st.expander("Upload a local video file"):
    upload = st.file_uploader("Drop an MP4, MOV, MKV, or WebM", type=["mp4", "mov", "mkv", "webm"], label_visibility="collapsed")
    if upload is not None:
        target = st.session_state.data_root / f"upload-{int(time.time())}-{upload.name}"
        target.write_bytes(upload.read())
        with st.spinner("Processing uploaded video..."):
            v = _process_video(str(target))
        if v:
            st.session_state.videos.append(v)
            st.session_state.display_log.append({"role": "user", "kind": "video", "video": v})
            st.rerun()


for entry in st.session_state.display_log:
    _render_log_entry(entry)


if st.session_state.pending_custom_goal:
    with st.form("custom_goal_form", clear_on_submit=True):
        goal = st.text_area(
            "What are you trying to achieve with this analysis?",
            placeholder="e.g. 'Find the strongest 5-second clip I could turn into a LinkedIn ad'",
            height=100,
        )
        submit = st.form_submit_button("Run analysis with this goal")
        if submit and goal.strip():
            st.session_state.pending_custom_goal = False
            _run_preset(PRESETS["custom_goal"], user_goal=goal.strip())
            st.rerun()
        elif submit:
            st.warning("Add a goal first.")


placeholder_text = (
    "Paste a video URL, ask a follow-up question, or describe what you want..."
    if st.session_state.videos
    else "Paste a video URL to start (YouTube, Loom, Vimeo, Reel, raw MP4...)"
)

if msg := st.chat_input(placeholder_text):
    msg = msg.strip()
    url_match = URL_RE.search(msg)
    if url_match:
        url = url_match.group(0).rstrip(",.;)")
        with st.spinner(f"Processing {url}..."):
            v = _process_video(url)
        if v:
            st.session_state.videos.append(v)
            st.session_state.display_log.append({"role": "user", "kind": "video", "video": v})
            extra = URL_RE.sub("", msg).strip()
            if extra:
                st.session_state.display_log.append({"role": "user", "kind": "text", "body": extra})
                _run_preset(PRESETS["custom_goal"], user_goal=extra)
        st.rerun()
    else:
        _run_followup(msg)
        st.rerun()
