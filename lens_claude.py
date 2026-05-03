"""Legacy shim - the real AI module is now lens_ai.py (Groq + Llama)."""
from lens_ai import (  # noqa: F401
    DEFAULT_MAX_TOKENS, DEFAULT_MODEL, ChatTurn,
    build_assistant_turn, build_followup_turn, build_initial_turn,
    build_remix_turn, make_client, stream_response,
)
