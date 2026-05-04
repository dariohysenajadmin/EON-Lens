"""
theme.py - Lens visual styling.

Streamlit's built-in theme system handles the base palette (configured in
.streamlit/config.toml). This module adds Lens-specific brand styling on top:
the wordmark, the chip row, frame gallery, and small polish touches.

We intentionally do NOT fight Streamlit's defaults for chat/input/expander
components - they work correctly with the configured theme.
"""

from __future__ import annotations


_BRAND_CSS = """\
<style>
:root {
  --lens-radius: 14px;
  --lens-radius-sm: 8px;
  --lens-accent: #d4622a;
  --lens-accent-soft: rgba(212, 98, 42, 0.18);
}

/* Brand wordmark */
.lens-brand {
  font-weight: 700;
  font-size: 1.5rem;
  letter-spacing: -0.02em;
  display: flex;
  align-items: center;
  gap: 8px;
}
.lens-brand .lens-dot {
  width: 10px; height: 10px;
  border-radius: 50%;
  background: var(--lens-accent);
  box-shadow: 0 0 12px var(--lens-accent);
  flex-shrink: 0;
}

.lens-tagline {
  font-size: 0.9rem;
  opacity: 0.65;
  margin-bottom: 18px;
}

/* Hide Streamlit's "Deploy" button and footer chrome */
.stDeployButton, footer { display: none !important; }
header[data-testid="stHeader"] { background: transparent !important; }

/* Frame thumbnails inside chat */
.lens-frames {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.lens-frames img {
  height: 64px;
  width: auto;
  border-radius: 4px;
  border: 1px solid rgba(128,128,128,0.25);
}

/* Video card in sidebar */
.lens-video-card {
  border: 1px solid rgba(128,128,128,0.25);
  border-radius: var(--lens-radius-sm);
  padding: 10px 12px;
  margin-bottom: 8px;
  font-size: 0.85rem;
}
.lens-video-card .title {
  font-weight: 600;
  margin-bottom: 4px;
  word-break: break-word;
}
.lens-video-card .meta {
  opacity: 0.65;
  font-size: 0.75rem;
}

/* Soft glow on focused inputs */
.stTextInput input:focus,
.stTextArea textarea:focus,
[data-testid="stChatInput"] textarea:focus {
  border-color: var(--lens-accent) !important;
  box-shadow: 0 0 0 3px var(--lens-accent-soft) !important;
}

/* Sticky chip row: target the columns block immediately after our anchor.
   The anchor is invisible; it's just a CSS hook for :has() to find the
   following element-container (the one that holds our 5 buttons). */
[data-testid="stElementContainer"]:has(> .stMarkdown .lens-chip-anchor),
[data-testid="element-container"]:has(> .stMarkdown .lens-chip-anchor) {
  display: none;
}
[data-testid="stElementContainer"]:has(> .stMarkdown .lens-chip-anchor) + [data-testid="stElementContainer"],
[data-testid="element-container"]:has(> .stMarkdown .lens-chip-anchor) + [data-testid="element-container"] {
  position: sticky;
  top: 3rem;
  z-index: 99;
  background: rgba(15, 17, 21, 0.92);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  padding: 10px 8px;
  border-radius: 12px;
  border-bottom: 1px solid rgba(212, 98, 42, 0.18);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.25);
  margin-bottom: 12px;
}
</style>
"""


def apply_theme(name: str = "light") -> str:
    """Return the brand CSS to inject. The 'name' arg is ignored - the base
    theme is set in .streamlit/config.toml. Kept for app.py compatibility."""
    return _BRAND_CSS
