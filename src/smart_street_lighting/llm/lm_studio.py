"""
OpenAI-compatible LLM client.

The same client talks to **any** endpoint that implements the OpenAI
chat-completions / embeddings schema:

* LM Studio (local, default -- no api_key needed)
* OpenRouter, Groq, Together, OpenAI proper (cloud -- api_key required)
* Ollama, vLLM (local -- no api_key needed)

Two layers:

1. :func:`chat_completion` and :func:`embed` -- plain ``requests``
   helpers. The notebook can use them directly without LlamaIndex.
2. :class:`OpenAICompatibleLLM` / :class:`OpenAICompatibleEmbedding`
   -- LlamaIndex adapters for :class:`VectorStoreIndex` and the
   query engine. Imported lazily so the base library does not depend
   on ``llama_index`` for non-RAG callers. The legacy
   ``LMStudioLLM`` / ``LMStudioEmbedding`` names remain as aliases
   for backwards compatibility.

All configuration (base URL, model names, api_key, timeouts) is
passed in by the notebook to keep model choice visible to the marker.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

import requests


DEFAULT_BASE_URL = "http://localhost:1234/v1"
DEFAULT_LLM_MODEL = "qwen2.5-7b-instruct"
DEFAULT_EMBED_MODEL = "text-embedding-nomic-embed-text-v1.5"
DEFAULT_TIMEOUT: tuple[int, int] = (10, 120)


def _build_headers(api_key: Optional[str]) -> dict:
    """Bearer-token auth header when an api_key is supplied (cloud providers)."""
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def chat_completion(
    messages: list[dict],
    model: str = DEFAULT_LLM_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    timeout: tuple[int, int] = DEFAULT_TIMEOUT,
    api_key: Optional[str] = None,
) -> str:
    """
    Call ``/v1/chat/completions`` and return the assistant's text.

    ``messages`` follows the OpenAI schema:
    ``[{"role": "system"|"user"|"assistant", "content": str}, ...]``.

    Pass ``api_key`` to authenticate with a cloud provider (OpenRouter,
    Groq, OpenAI, ...). Omit it for local LM Studio / Ollama / vLLM.
    """
    resp = requests.post(
        f"{base_url}/chat/completions",
        json={
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        headers=_build_headers(api_key),
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def embed(
    texts: list[str],
    model: str = DEFAULT_EMBED_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    timeout: tuple[int, int] = DEFAULT_TIMEOUT,
    api_key: Optional[str] = None,
) -> list[list[float]]:
    """Call ``/v1/embeddings`` and return one float vector per input.

    Pass ``api_key`` for cloud providers; omit for local LM Studio.
    Note: OpenRouter does not currently expose embeddings -- if you
    use OpenRouter for chat, keep LM Studio (or another endpoint) for
    embeddings.
    """
    resp = requests.post(
        f"{base_url}/embeddings",
        json={"model": model, "input": texts},
        headers=_build_headers(api_key),
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]


# ----------------------------------------------------------------
# LlamaIndex adapters (imported lazily)
# ----------------------------------------------------------------

def _llama_index_imports():
    """Import the LlamaIndex symbols we need, with a helpful error."""
    try:
        from llama_index.core.bridge.pydantic import PrivateAttr
        from llama_index.core.embeddings import BaseEmbedding
        from llama_index.core.llms import (
            ChatMessage,
            ChatResponse,
            CompletionResponse,
            CustomLLM,
            LLMMetadata,
        )
        from llama_index.core.llms.callbacks import (
            llm_chat_callback,
            llm_completion_callback,
        )
    except ImportError as e:
        raise ImportError(
            "LlamaIndex is required for LMStudioLLM/LMStudioEmbedding. "
            "Install with: pip install 'smart-street-lighting-plugin[rag]'"
        ) from e
    return (
        PrivateAttr,
        BaseEmbedding,
        ChatMessage,
        ChatResponse,
        CompletionResponse,
        CustomLLM,
        LLMMetadata,
        llm_chat_callback,
        llm_completion_callback,
    )


class _LazyLMStudioEmbedding:
    """Sentinel; real class is created on first access (see __getattr__)."""


def _build_classes():
    (
        PrivateAttr,
        BaseEmbedding,
        ChatMessage,
        ChatResponse,
        CompletionResponse,
        CustomLLM,
        LLMMetadata,
        llm_chat_callback,
        llm_completion_callback,
    ) = _llama_index_imports()

    class OpenAICompatibleEmbedding(BaseEmbedding):
        """LlamaIndex embedding for any OpenAI-compatible ``/embeddings`` endpoint."""

        _api_url: str = PrivateAttr()
        _model: str = PrivateAttr()
        _timeout: tuple = PrivateAttr()
        _api_key: Optional[str] = PrivateAttr()

        def __init__(
            self,
            api_base: str = DEFAULT_BASE_URL,
            model: str = DEFAULT_EMBED_MODEL,
            embed_batch_size: int = 10,
            timeout: tuple[int, int] = DEFAULT_TIMEOUT,
            api_key: Optional[str] = None,
        ):
            super().__init__(model_name=model, embed_batch_size=embed_batch_size)
            self._api_url = f"{api_base}/embeddings"
            self._model = model
            self._timeout = timeout
            self._api_key = api_key

        def _call_api(self, texts: List[str]) -> List[List[float]]:
            resp = requests.post(
                self._api_url,
                json={"model": self._model, "input": texts},
                headers=_build_headers(self._api_key),
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            sorted_data = sorted(data["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in sorted_data]

        def _get_query_embedding(self, query: str) -> List[float]:
            return self._call_api([query])[0]

        def _get_text_embedding(self, text: str) -> List[float]:
            return self._call_api([text])[0]

        async def _aget_query_embedding(self, query: str) -> List[float]:
            return self._get_query_embedding(query)

        async def _aget_text_embedding(self, text: str) -> List[float]:
            return self._get_text_embedding(text)

    class OpenAICompatibleLLM(CustomLLM):
        """LlamaIndex LLM for any OpenAI-compatible ``/chat/completions`` endpoint."""

        model_name: str = DEFAULT_LLM_MODEL
        api_base: str = DEFAULT_BASE_URL
        api_key: Optional[str] = None
        max_tokens: int = 2048
        temperature: float = 0.3
        context_window: int = 8192
        request_timeout: tuple = DEFAULT_TIMEOUT

        @property
        def metadata(self) -> LLMMetadata:
            return LLMMetadata(
                context_window=self.context_window,
                num_output=self.max_tokens,
                model_name=self.model_name,
                is_chat_model=True,
            )

        @llm_completion_callback()
        def complete(self, prompt: str, **kwargs: Any) -> CompletionResponse:
            text = chat_completion(
                [{"role": "user", "content": prompt}],
                model=self.model_name,
                base_url=self.api_base,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                timeout=tuple(self.request_timeout),
                api_key=self.api_key,
            )
            return CompletionResponse(text=text)

        @llm_chat_callback()
        def chat(self, messages: Sequence[ChatMessage], **kwargs: Any) -> ChatResponse:
            api_messages = [
                {
                    "role": msg.role.value if hasattr(msg.role, "value") else str(msg.role),
                    "content": msg.content,
                }
                for msg in messages
            ]
            text = chat_completion(
                api_messages,
                model=self.model_name,
                base_url=self.api_base,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                timeout=tuple(self.request_timeout),
                api_key=self.api_key,
            )
            return ChatResponse(message=ChatMessage(role="assistant", content=text))

        @llm_completion_callback()
        def stream_complete(self, prompt: str, **kwargs: Any):
            return self.complete(prompt, **kwargs)

        @llm_chat_callback()
        def stream_chat(self, messages: Sequence[ChatMessage], **kwargs: Any):
            return self.chat(messages, **kwargs)

    # Legacy aliases for backwards compatibility.
    LMStudioLLM = OpenAICompatibleLLM
    LMStudioEmbedding = OpenAICompatibleEmbedding

    return OpenAICompatibleLLM, OpenAICompatibleEmbedding


_classes: Optional[tuple] = None

_LAZY_CLASS_NAMES = {
    "OpenAICompatibleLLM",
    "OpenAICompatibleEmbedding",
    "LMStudioLLM",          # legacy alias
    "LMStudioEmbedding",    # legacy alias
}


def __getattr__(name: str):
    """
    Lazy-load LlamaIndex-dependent classes so importing
    ``smart_street_lighting.llm`` doesn't require LlamaIndex.
    """
    global _classes
    if name in _LAZY_CLASS_NAMES:
        if _classes is None:
            _classes = _build_classes()
        llm_cls, emb_cls = _classes
        return {
            "OpenAICompatibleLLM":       llm_cls,
            "OpenAICompatibleEmbedding": emb_cls,
            "LMStudioLLM":               llm_cls,
            "LMStudioEmbedding":         emb_cls,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
