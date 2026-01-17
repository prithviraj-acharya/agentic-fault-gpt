"""Phase 5: Retrieval helpers for dynamic window history collection."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from dotenv import load_dotenv

from dynamic_layer.config import load_settings

load_dotenv()

try:
    # Preferred: supports `python -m dynamic_layer.retrievers`
    from static_layer.openai_embedder import OpenAIEmbeddingFunction
except Exception:  # pragma: no cover
    from openai_embedder import OpenAIEmbeddingFunction


def _get_collection(collection_name: str | None = None):
    try:
        import chromadb  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Missing dependency: chromadb. Install with `pip install chromadb`."
        ) from exc

    settings = load_settings()
    client = chromadb.PersistentClient(
        path=str(Path(settings.chroma_persist_dir).resolve())
    )
    embed_fn = OpenAIEmbeddingFunction(model=settings.openai_embedding_model)
    collection = client.get_or_create_collection(
        name=collection_name or settings.chroma_collection,
        metadata={"hnsw:space": "cosine"},
        embedding_function=cast(Any, embed_fn),
    )
    return collection


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
        results.append(
            {
                "id": _id,
                "score": dist,
                "text": text,
                "metadata": md,
            }
        )
    return results


def retrieve_window_history(
    query: str, top_k: int = 5, where: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    collection = _get_collection(collection_name="window_history")
    raw = collection.query(
        query_texts=[query],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    return _format_results(raw)


def retrieve_incident_history(
    query: str, top_k: int = 5, where: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    collection = _get_collection(collection_name="incident_history")
    raw = collection.query(
        query_texts=[query],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    return _format_results(raw)
