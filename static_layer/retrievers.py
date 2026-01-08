"""Phase 4: Retrieval helpers for static knowledge collections.

Collections:
- manuals: chunked PDF manual text with provenance metadata
- past_cases: JSONL past cases with structured embedding text

Both collections live in persistent Chroma at ./chroma_db.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

# Load environment variables for OpenAI
from dotenv import load_dotenv

load_dotenv()

# Use OpenAI embedding function (works for both module/script execution)
try:
    # Preferred: supports `python -m static_layer.retrievers`
    from static_layer.openai_embedder import OpenAIEmbeddingFunction
except Exception:  # pragma: no cover
    # Fallback: supports running from within static_layer
    from openai_embedder import OpenAIEmbeddingFunction

## HashEmbeddingFunction removed; now using OpenAIEmbeddingFunction


def _get_client_and_collections():
    try:
        import chromadb  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Missing dependency: chromadb. Install with `pip install chromadb`."
        ) from exc

    client = chromadb.PersistentClient(path=str(Path("chroma_db").resolve()))
    embed_fn = OpenAIEmbeddingFunction()

    manuals = client.get_or_create_collection(
        name="manuals",
        metadata={"hnsw:space": "cosine"},
        embedding_function=cast(Any, embed_fn),
    )
    past_cases = client.get_or_create_collection(
        name="past_cases",
        metadata={"hnsw:space": "cosine"},
        embedding_function=cast(Any, embed_fn),
    )
    return manuals, past_cases


def _format_results(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    ids = (raw.get("ids") or [[]])[0]
    docs = (raw.get("documents") or [[]])[0]
    metas = (raw.get("metadatas") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]

    results: List[Dict[str, Any]] = []
    for i, _id in enumerate(ids):
        text = docs[i] if i < len(docs) else ""
        md = metas[i] if i < len(metas) else {}
        dist = distances[i] if i < len(distances) else None

        snippet = (text or "").replace("\n", " ").strip()
        if len(snippet) > 260:
            snippet = snippet[:260] + "..."

        results.append(
            {
                "id": _id,
                "score": dist,
                "text_snippet": snippet,
                "metadata": md,
            }
        )
    return results


def retrieve_manuals(
    query: str, top_k: int = 5, where: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    manuals, _ = _get_client_and_collections()
    raw = manuals.query(
        query_texts=[query],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    return _format_results(raw)


def retrieve_past_cases(
    query: str, top_k: int = 5, where: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    _, past_cases = _get_client_and_collections()
    raw = past_cases.query(
        query_texts=[query],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    return _format_results(raw)
