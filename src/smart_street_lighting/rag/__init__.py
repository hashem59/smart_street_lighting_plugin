"""
Retrieval-Augmented Generation (RAG) helpers.

Wires up:

* a ChromaDB persistent vector store,
* a LlamaIndex ``VectorStoreIndex`` ingested from a directory of
  ``.md`` / ``.txt`` / ``.pdf`` knowledge-base documents,
* an LM Studio embedding model + chat model for retrieval and
  response synthesis.

The notebook keeps the prompt template and the LLM model name inline,
and the marker can see exactly which knowledge sources were
indexed.
"""

from smart_street_lighting.rag.pipeline import (
    create_chroma_client,
    ingest_documents,
    load_existing_index,
    create_query_engine,
    query_with_context,
    DEFAULT_SOURCE_RULES,
)

__all__ = [
    "create_chroma_client",
    "ingest_documents",
    "load_existing_index",
    "create_query_engine",
    "query_with_context",
    "DEFAULT_SOURCE_RULES",
]
