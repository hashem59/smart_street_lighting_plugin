"""
OpenAI-compatible LLM client.

Thin LlamaIndex adapters that talk to any endpoint speaking the
OpenAI chat-completions / embeddings schema (LM Studio, OpenRouter,
Groq, Together, Ollama, vLLM, OpenAI proper, ...). Models, the base
URL, and any api_key are passed in by the notebook so the marker can
see exactly which provider was used.

``chat_completion`` and ``embed`` are always available; the
LlamaIndex adapters (``OpenAICompatibleLLM`` /
``OpenAICompatibleEmbedding`` -- with legacy aliases
``LMStudioLLM`` / ``LMStudioEmbedding``) are imported lazily so
callers without LlamaIndex don't pay for the import.
"""

from smart_street_lighting.llm.lm_studio import chat_completion, embed

__all__ = [
    "OpenAICompatibleLLM",
    "OpenAICompatibleEmbedding",
    "LMStudioLLM",
    "LMStudioEmbedding",
    "chat_completion",
    "embed",
]


_LAZY = {
    "OpenAICompatibleLLM",
    "OpenAICompatibleEmbedding",
    "LMStudioLLM",
    "LMStudioEmbedding",
}


def __getattr__(name: str):
    if name in _LAZY:
        from smart_street_lighting.llm import lm_studio

        return getattr(lm_studio, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
