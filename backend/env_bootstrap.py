"""
Map OPENROUTER_API_KEY to OPENAI_API_KEY / OPENAI_BASE_URL when no OpenAI key is set.

Inference uses Bedrock via LitellmModel; this only helps optional OpenAI-compatible
clients (e.g. tracing) that read OPENAI_API_KEY.
"""

from __future__ import annotations

import os

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"


def apply_openrouter_openai_aliases() -> None:
    """If OPENROUTER_API_KEY is set and OPENAI_API_KEY is empty, alias for OpenAI-compatible SDKs."""
    router = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not router:
        return
    existing = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if existing:
        return
    os.environ["OPENAI_API_KEY"] = router
    if not (os.environ.get("OPENAI_BASE_URL") or "").strip():
        os.environ["OPENAI_BASE_URL"] = OPENROUTER_API_BASE
