"""
theme.py - dark / light theme CSS for Lens.

Streamlit doesn't expose a runtime theme switch via the public API, so
we inject CSS variables that override the page chrome. Both themes
target the same DOM tree; only the variable values change.
"""

from __future__ import annotations


_BASE_CSS = """\
<style>
:root {
  --lens-radius: 14px;
  --lens-radius-sm: 8px;
  --lens-mono: 'JetBrains Mono', 'SF Mono', Menlo, Consolas, monospace;
  --lens-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
}

/* App shell */
.stApp {
  background: var(--lens-bg) !important;
  color: var(--lens-fg) !important;
}

/* Hide Streamlit's default header/footer chrome */
header[data-testid="stHeader"] {
  background: transparent !important;
}
.stDeployButton, footer { display: none !important; }

/* Sidebar */
section[data-testid="stSidebar"] {
  background: var(--lens-sidebar) !important;
  border-right: 1px solid var(--lens-border) !important;
}
section[data-testid="stSidebar"] * {
  color: var(--lens-fg) !important;
}

/* Headings */
h1, h2, h3, h4, h5 { color: var(--lens-fg) !important; font-family: var(--lens-sans); }

/* Chat messages */
[data-testid="stChatMessage"] {
  background: var(--lens-card) !important;
  border: 1px solid var(--lens-border);
  border-radius: var(--lens-radius);
  padding: 12px 16px !important;
  margin-bottom: 12px;
}
[data-testid="stChatMessage"] p,
[data-testid="stChatMessage"] li,
[data-testid="stChatMessage"] span,
[data-testid="stChatMessage"] code {
  color: var(--lens-fg) !important;
}

/* User vs assistant message tinting */
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
  background: var(--lens-card-user) !important;
}

/* Chat input area */
[data-testid="stChatInput"] textarea {
  background: var(--lens-input) !important;
  color: var(--lens-fg) !important;
  border: 1px solid var(--lens-border) !important;
  border-radius: var(--lens-radius) !important;
  font-family: var(--lens-sans);
}
[data-testid="stChatInput"] textarea:focus {
  border-color: var(--lens-accent) !important;
  outline: none !important;
  box-shadow: 0 0 0 3px var(--lens-accent-soft) !important;
}

/* Buttons */
.stButton > button, .stDownloadButton > button {
  background: var(--lens-accent) !important;
  color: var(--lens-on-accent) !important;
  border: none !important;
  border-radius: var(--lens-radius-sm) !important;
  font-weight: 600 !important;
  transition: transform 0.08s ease, opacity 0.15s ease;
}
.stButton > button:hover { opacity: 0.9; transform: translateY(-1px); }
.stButton > button:active { transform: translateY(0); }

/* Secondary (preset chips & remix) */
.lens-chip-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
.lens-chip-row .stButton > button {
  background: var(--lens-chip) !important;
  color: var(--lens-fg) !important;
  border: 1px solid var(--lens-border) !important;
  font-weight: 500 !important;
  font-size: 0.875rem !important;
  padding: 6px 14px !important;
}
.lens-chip-row .stButton > button:hover {
  background: var(--lens-chip-hover) !important;
  border-color: var(--lens-accent) !important;
}

/* Inputs */
.stTextInput input, .stTextArea textarea {
  background: var(--lens-input) !important;
  color: var(--lens-fg) !important;
  border: 1px solid var(--lens-border) !important;
  border-radius: var(--lens-radius-sm) !important;
}

/* Status / info banners */
.stAlert {
  background: var(--lens-card) !important;
  border: 1px solid var(--lens-border) !important;
  border-radius: var(--lens-radius-sm) !important;
}

/* File uploader */
[data-testid="stFileUploaderDropzone"] {
  background: var(--lens-input) !important;
  border: 1px dashed var(--lens-border) !important;
  border-radius: var(--lens-radius) !important;
}

/* Dividers */
hr { border-color: var(--lens-border) !important; }

/* Brand wordmark */
.lens-brand {
  font-family: var(--lens-sans);
  font-weight: 700;
  font-size: 1.5rem;
  letter-spacing: -0.02em;
  color: var(--lens-fg);
  display: flex;
  align-items: center;
  gap: 8px;
}
.lens-brand .lens-dot {
  width: 10px; height: 10px;
  border-radius: 50%;
  background: var(--lens-accent);
  box-shadow: 0 0 12px var(--lens-accent);
}

.lens-tagline {
  font-size: 0.85rem;
  color: var(--lens-muted);
  margin-bottom: 18px;
}

/* Frame thumbnails inside chat */
.lens-frames { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.lens-frames img {
  height: 64px;
  width: auto;
  border-radius: 4px;
  border: 1px solid var(--lens-border);
}

/* Video card in sidebar */
.lens-video-card {
  background: var(--lens-card);
  border: 1px solid var(--lens-border);
  border-radius: var(--lens-radius-sm);
  padding: 10px 12px;
  margin-bottom: 8px;
  font-size: 0.85rem;
}
.lens-video-card .title {
  font-weight: 600;
  color: var(--lens-fg);
  margin-bottom: 4px;
  word-break: break-word;
}
.lens-video-card .meta {
  color: var(--lens-muted);
  font-size: 0.75rem;
}
</style>
"""

_DARK_VARS = """\
<style>
:root {
  --lens-bg: #0e1014;
  --lens-sidebar: #14171c;
  --lens-card: #1a1d23;
  --lens-card-user: #232830;
  --lens-input: #1a1d23;
  --lens-border: #2a2f37;
  --lens-fg: #e8eaed;
  --lens-muted: #9aa0a6;
  --lens-accent: #d4622a;          /* warm orange that matches Eon vibe */
  --lens-accent-soft: rgba(212, 98, 42, 0.18);
  --lens-on-accent: #ffffff;
  --lens-chip: #1a1d23;
  --lens-chip-hover: #232830;
}
</style>
"""

_LIGHT_VARS = """\
<style>
:root {
  --lens-bg: #fafafa;
  --lens-sidebar: #ffffff;
  --lens-card: #ffffff;
  --lens-card-user: #f3f4f6;
  --lens-input: #ffffff;
  --lens-border: #e5e7eb;
  --lens-fg: #111827;
  --lens-muted: #6b7280;
  --lens-accent: #d4622a;
  --lens-accent-soft: rgba(212, 98, 42, 0.12);
  --lens-on-accent: #ffffff;
  --lens-chip: #ffffff;
  --lens-chip-hover: #f3f4f6;
}
</style>
"""


def apply_theme(name: str) -> str:
    """Return the CSS string to inject for the given theme name ('dark'|'light')."""
    vars_block = _DARK_VARS if name == "dark" else _LIGHT_VARS
    return vars_block + _BASE_CSS
