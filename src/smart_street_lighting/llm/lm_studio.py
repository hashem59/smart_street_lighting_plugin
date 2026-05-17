"""
LM Studio adapters.

Two layers:

1. :func:`chat_completion` and :func:`embed` -- plain ``requests``
   helpers that talk to LM Studio's ``/v1/chat/completions`` and
   ``/v1/embeddings`` endpoints. The notebook can use these directly
   without LlamaIndex.
2. :class:`LMStudioLLM` and :class:`LMStudioEmbedding` -- LlamaIndex
   adapters for use with :class:`VectorStoreIndex` and the query
   engine. Imported lazily so the base library does not depend on
   ``llama_index`` for non-RAG callers.

All configuration (base URL, model names, timeouts) is passed in by
the notebook to keep model choice visible to the marker.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

import requests


DEFAULT_BASE_URL = "http://localhost:1234/v1"
DEFAULT_LLM_MODEL = "qwen2.5-7b-instruct"
DEFAULT_EMBED_MODEL = "text-embedding-nomic-embed-text-v1.5"
DEFAULT_TIMEOUT: tuple[int, int] = (10, 120)


def chat_completion(
    messages: list[dict],
    model: str = DEFAULT_LLM_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    timeout: tuple[int, int] = DEFAULT_TIMEOUT,
) -> str:
    """
    Call ``/v1/chat/completions`` and return the assistant's text.

    ``messages`` follows the OpenAI schema:
    ``[{"role": "system"|"user"|"assistant", "content": str}, ...]``.
    """
    resp = requests.post(
        f"{base_url}/chat/completions",
        json={
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def embed(
    texts: list[str],
    model: str = DEFAULT_EMBED_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    timeout: tuple[int, int] = DEFAULT_TIMEOUT,
) -> list[list[float]]:
    """Call ``/v1/embeddings`` and return one float vector per input."""
    resp = requests.post(
        f"{base_url}/embeddings",
        json={"model": model, "input": texts},
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

    class LMStudioEmbedding(BaseEmbedding):
        """LlamaIndex embedding backed by LM Studio's ``/embeddings`` endpoint."""

        _api_url: str = PrivateAttr()
        _model: str = PrivateAttr()
        _timeout: tuple = PrivateAttr()

        def __init__(
            self,
            api_base: str = DEFAULT_BASE_URL,
            model: str = DEFAULT_EMBED_MODEL,
            embed_batch_size: int = 10,
            timeout: tuple[int, int] = DEFAULT_TIMEOUT,
        ):
            super().__init__(model_name=model, embed_batch_size=embed_batch_size)
            self._api_url = f"{api_base}/embeddings"
            self._model = model
            self._timeout = timeout

        def _call_api(self, texts: List[str]) -> List[List[float]]:
            resp = requests.post(
                self._api_url,
                json={"model": self._model, "input": texts},
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

    class LMStudioLLM(CustomLLM):
        """LlamaIndex LLM backed by LM Studio's ``/chat/completions``."""

        model_name: str = DEFAULT_LLM_MODEL
        api_base: str = DEFAULT_BASE_URL
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
            )
            return ChatResponse(message=ChatMessage(role="assistant", content=text))

        @llm_completion_callback()
        def stream_complete(self, prompt: str, **kwargs: Any):
            return self.complete(prompt, **kwargs)

        @llm_chat_callback()
        def stream_chat(self, messages: Sequence[ChatMessage], **kwargs: Any):
            return self.chat(messages, **kwargs)

    return LMStudioLLM, LMStudioEmbedding


_classes: Optional[tuple] = None


def __getattr__(name: str):
    """
    Module-level lazy loader for the LlamaIndex-dependent classes so
    importing ``smart_street_lighting.llm`` doesn't require LlamaIndex.
    """
    global _classes
    if name in {"LMStudioLLM", "LMStudioEmbedding"}:
        if _classes is None:
            _classes = _build_classes()
        llm_cls, emb_cls = _classes
        return {"LMStudioLLM": llm_cls, "LMStudioEmbedding": emb_cls}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
