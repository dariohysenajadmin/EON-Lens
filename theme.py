"""
theme.py - Lens visual styling.

Streamlit's built-in theme system handles the base palette (configured in
.streamlit/config.toml). This module adds Lens-specific brand styling on top.
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

.stDeployButton, footer { display: none !important; }
header[data-testid="stHeader"] { background: transparent !important; }

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

.stTextInput input:focus,
.stTextArea textarea:focus,
[data-testid="stChatInput"] textarea:focus {
  border-color: var(--lens-accent) !important;
  box-shadow: 0 0 0 3px var(--lens-accent-soft) !important;
}
</style>
"""


def apply_theme(name: str = "light") -> str:
    """Return brand CSS. The 'name' arg is ignored - base theme is in config.toml."""
    return _BRAND_CSS
