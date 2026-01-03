"""Phase 4: Retrieval helpers for static knowledge collections.

Collections:
- manuals: chunked PDF manual text with provenance metadata
- past_cases: JSONL past cases with structured embedding text

Both collections live in persistent Chroma at ./chroma_db.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class HashEmbeddingFunction:
    """Deterministic, fully-local embedding based on feature hashing.

    Important: the same embedding function must be used for both indexing and querying.
    """

    def __init__(self, dim: int = 1024, seed: str = "hvac-fdd-v1") -> None:
        self.dim = dim
        self.seed = seed

    def name(self) -> str:
        return "hash-embedding-v1"

    def get_config(self) -> dict:
        return {"dim": self.dim, "seed": self.seed}

    @classmethod
    def build_from_config(cls, config: dict) -> "HashEmbeddingFunction":
        return cls(**(config or {}))

    def _tokenize(self, text: str) -> List[str]:
        text = text.lower()
        tokens = re.findall(r"[a-z0-9_]+", text)
        return [t for t in tokens if len(t) >= 2]

    def _hash_to_index_and_sign(self, token: str) -> Tuple[int, int]:
        h = hashlib.md5((self.seed + "::" + token).encode("utf-8")).hexdigest()
        val = int(h, 16)
        idx = val % self.dim
        sign = 1 if (val >> 1) % 2 == 0 else -1
        return idx, sign

    def __call__(self, input: List[str]) -> List[List[float]]:
        vectors: List[List[float]] = []
        for text in input:
            vec = [0.0] * self.dim
            for tok in self._tokenize(text):
                idx, sign = self._hash_to_index_and_sign(tok)
                vec[idx] += float(sign)
            norm_sq = sum(v * v for v in vec)
            if norm_sq > 0:
                norm = norm_sq**0.5
                vec = [v / norm for v in vec]
            vectors.append(vec)
        return vectors

    def embed_documents(
        self,
        texts: List[str] | None = None,
        *,
        input: List[str] | None = None,
        **_: object,
    ) -> List[List[float]]:
        payload = input if input is not None else (texts or [])
        return self(payload)

    def embed_query(
        self,
        text: str | None = None,
        *,
        input: str | List[str] | None = None,
        **_: object,
    ):
        payload = input if input is not None else (text or "")
        if isinstance(payload, list):
            return self([str(x) for x in payload])
        return self([str(payload)])[0]


def _get_client_and_collections():
    try:
        import chromadb  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Missing dependency: chromadb. Install with `pip install chromadb`."
        ) from exc

    client = chromadb.PersistentClient(path=str(Path("chroma_db").resolve()))
    embed_fn = HashEmbeddingFunction(dim=1024)

    manuals = client.get_or_create_collection(
        name="manuals",
        metadata={"hnsw:space": "cosine"},
        embedding_function=embed_fn,
    )
    past_cases = client.get_or_create_collection(
        name="past_cases",
        metadata={"hnsw:space": "cosine"},
        embedding_function=embed_fn,
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
