"""
LM Studio client.

Thin LlamaIndex-compatible adapters that call LM Studio's
OpenAI-compatible HTTP API directly. Models and the base URL are
passed in by the notebook, so the marker can see exactly which models
were used.

``chat_completion`` and ``embed`` are always available; the
LlamaIndex adapters (``LMStudioLLM``, ``LMStudioEmbedding``) are
imported lazily so callers without LlamaIndex don't pay for the import.
"""

from smart_street_lighting.llm.lm_studio import chat_completion, embed

__all__ = [
    "LMStudioLLM",
    "LMStudioEmbedding",
    "chat_completion",
    "embed",
]


def __getattr__(name: str):
    if name in {"LMStudioLLM", "LMStudioEmbedding"}:
        from smart_street_lighting.llm import lm_studio

        return getattr(lm_studio, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
