"""
RAG ingestion and query pipeline.

The original codebase had this split across ``rag/ingest.py`` and
``rag/query_engine.py``. Here it is collapsed to one module because
the notebook calls the two halves back-to-back.

Knowledge-base paths, the system prompt, and model names all live in
the notebook so the marker can see them. The functions in this file
just plumb the LlamaIndex / ChromaDB pieces together.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Sequence


# Default source-type tagging rules used by ``ingest_documents``. The
# notebook can override or extend these without subclassing.
DEFAULT_SOURCE_RULES: list[tuple[str, str, str]] = [
    ("as_nzs_1158",          "standard",   "AS/NZS 1158"),
    ("pedestrian_crossing",  "standard",   "AS/NZS 1158.4"),
    ("energy",               "guideline",  "Energy Efficiency Guidelines"),
    ("solar",                "guideline",  "Solar Lighting Guidelines"),
    ("adaptive_dimming",     "guideline",  "Adaptive Dimming Guidelines"),
    ("methodology",          "guideline",  "Lighting Design Methodology"),
    ("event",                "guideline",  "Event Lighting Guidelines"),
    ("melbourne",            "urban_data", "Melbourne Urban Data"),
    ("nga_factors",          "guideline",  "National Greenhouse Accounts"),
    ("bom_",                 "urban_data", "Bureau of Meteorology"),
]


def _require_llama_index():
    try:
        from llama_index.core import (  # noqa: F401
            SimpleDirectoryReader,
            StorageContext,
            VectorStoreIndex,
        )
        from llama_index.core.node_parser import SentenceSplitter  # noqa: F401
        from llama_index.core.query_engine import RetrieverQueryEngine  # noqa: F401
        from llama_index.core.prompts import PromptTemplate  # noqa: F401
        from llama_index.core.response_synthesizers import (  # noqa: F401
            get_response_synthesizer,
        )
        from llama_index.core.retrievers import VectorIndexRetriever  # noqa: F401
        from llama_index.vector_stores.chroma import ChromaVectorStore  # noqa: F401
        import chromadb  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "RAG features require LlamaIndex + ChromaDB. "
            "Install with: pip install 'smart-street-lighting-plugin[rag]'"
        ) from e


def create_chroma_client(persist_dir: Path | str):
    """Create a persistent ChromaDB client at ``persist_dir``."""
    _require_llama_index()
    import chromadb

    persist_dir = Path(persist_dir)
    persist_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(persist_dir))


def _tag_documents(documents, source_rules: Sequence[tuple[str, str, str]]):
    for doc in documents:
        filename = (doc.metadata.get("file_name") or "unknown").lower()
        doc.metadata["source_type"] = "other"
        doc.metadata["source"] = doc.metadata.get("file_name", "unknown")
        for keyword, src_type, src_name in source_rules:
            if keyword in filename:
                doc.metadata["source_type"] = src_type
                doc.metadata["source"] = src_name
                break


def ingest_documents(
    source_dirs: Iterable[Path | str],
    persist_dir: Path | str,
    embed_model,
    collection_name: str = "street_lighting_kb",
    chunk_size: int = 1024,
    chunk_overlap: int = 100,
    source_rules: Optional[Sequence[tuple[str, str, str]]] = None,
    required_exts: Sequence[str] = (".md", ".txt", ".pdf"),
):
    """
    Build a ``VectorStoreIndex`` from one or more knowledge-base directories.

    Args:
        source_dirs: Directories to recursively scan.
        persist_dir: Where ChromaDB stores its persistent files.
        embed_model: A LlamaIndex-compatible embedding model (typically
            ``LMStudioEmbedding(...)``).
        collection_name: ChromaDB collection name; recreated each run.
        chunk_size, chunk_overlap: Sentence-splitter parameters.
        source_rules: Filename-keyword to (source_type, source_name)
            mapping used to tag chunks; defaults to
            :data:`DEFAULT_SOURCE_RULES`.
        required_exts: File extensions to include.
    """
    _require_llama_index()
    from llama_index.core import (
        SimpleDirectoryReader,
        StorageContext,
        VectorStoreIndex,
    )
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.vector_stores.chroma import ChromaVectorStore

    if source_rules is None:
        source_rules = DEFAULT_SOURCE_RULES

    documents = []
    for source_dir in source_dirs:
        source_dir = Path(source_dir)
        if source_dir.exists():
            print(f"Loading documents from {source_dir}...")
            reader = SimpleDirectoryReader(
                input_dir=str(source_dir),
                recursive=True,
                required_exts=list(required_exts),
            )
            docs = reader.load_data()
            documents.extend(docs)
            print(f"  Loaded {len(docs)} files from {source_dir.name}")

    print(f"Total documents loaded: {len(documents)}")
    _tag_documents(documents, source_rules)

    splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    chroma_client = create_chroma_client(persist_dir)
    try:
        chroma_client.delete_collection(collection_name)
        print(f"Deleted existing collection '{collection_name}'.")
    except Exception:
        pass

    chroma_collection = chroma_client.get_or_create_collection(collection_name)
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    print("Chunking + embedding documents...")
    index = VectorStoreIndex.from_documents(
        documents,
        storage_context=storage_context,
        transformations=[splitter],
        embed_model=embed_model,
        show_progress=True,
    )

    num_chunks = chroma_collection.count()
    print(f"Ingestion complete. {num_chunks} chunks stored in ChromaDB.")
    return index


def load_existing_index(
    persist_dir: Path | str,
    embed_model,
    collection_name: str = "street_lighting_kb",
):
    """Load a previously-ingested ChromaDB collection without re-embedding."""
    _require_llama_index()
    from llama_index.core import VectorStoreIndex
    from llama_index.vector_stores.chroma import ChromaVectorStore

    chroma_client = create_chroma_client(persist_dir)
    chroma_collection = chroma_client.get_collection(collection_name)
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

    index = VectorStoreIndex.from_vector_store(vector_store, embed_model=embed_model)
    print(f"Loaded existing index with {chroma_collection.count()} chunks.")
    return index


def create_query_engine(
    index,
    llm,
    system_prompt: str,
    similarity_top_k: int = 5,
    response_mode: str = "compact",
):
    """
    Build a RetrieverQueryEngine around an LM-Studio-backed LLM.

    The ``system_prompt`` is injected into the QA template so the LLM
    sees the report structure rules every call.
    """
    _require_llama_index()
    from llama_index.core.prompts import PromptTemplate
    from llama_index.core.query_engine import RetrieverQueryEngine
    from llama_index.core.response_synthesizers import get_response_synthesizer
    from llama_index.core.retrievers import VectorIndexRetriever

    retriever = VectorIndexRetriever(index=index, similarity_top_k=similarity_top_k)
    response_synthesizer = get_response_synthesizer(llm=llm, response_mode=response_mode)
    query_engine = RetrieverQueryEngine(
        retriever=retriever, response_synthesizer=response_synthesizer
    )

    qa_prompt = PromptTemplate(
        system_prompt + "\n\n"
        "Context information from the knowledge base:\n"
        "---------------------\n"
        "{context_str}\n"
        "---------------------\n\n"
        "Query: {query_str}\n\n"
        "Provide a detailed, professional design report response:"
    )
    query_engine.update_prompts({"response_synthesizer:text_qa_template": qa_prompt})
    return query_engine


def query_with_context(query_engine, user_query: str, calculation_context: str = ""):
    """
    Send ``user_query`` to ``query_engine``, optionally prefixed with
    the deterministic calculation context so the LLM grounds its
    numbers in the engine's authoritative output.
    """
    if calculation_context:
        full_query = (
            "CALCULATED DESIGN SPECIFICATIONS (these are correct, use them):\n"
            f"{calculation_context}\n\n"
            f"USER QUERY: {user_query}\n\n"
            "Using the calculated specs above and the retrieved knowledge base "
            "context, write a professional design report that explains and "
            "justifies this lighting design."
        )
    else:
        full_query = user_query
    return query_engine.query(full_query)
