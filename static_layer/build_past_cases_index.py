"""Phase 4: Build Chroma collection `past_cases` from local JSONL past cases.

- Reads: knowledge/past_cases/past_cases.jsonl
- Creates embedding text per case (prompt-specified format)
- Upserts into persistent Chroma DB at ./chroma_db, collection `past_cases`

Deterministic IDs:
  past case id == case_id

This script is idempotent: re-running upserts the same IDs (no duplicates).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class HashEmbeddingFunction:
    """Deterministic, fully-local embedding based on feature hashing."""

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


def join_list(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "|".join(str(x) for x in value)
    return str(value)


def build_case_embedding_text(case: Dict[str, Any]) -> str:
    case_id = case.get("case_id", "")
    fault_type = case.get("fault_type", "")
    title = case.get("fault_title", "")

    symptoms = join_list(case.get("symptoms"))

    wp = case.get("window_pattern") or {}
    persistence = wp.get("persistence_windows", "")
    severity = wp.get("severity", "")
    notes = wp.get("trend_notes", "")

    root_cause = case.get("likely_root_cause", "")
    verification = join_list(case.get("verification_steps"))
    resolution = join_list(case.get("resolution_steps"))
    expected = join_list(case.get("expected_post_fix_behavior"))
    tags = join_list(case.get("tags"))

    return (
        f"CASE_ID: {case_id}\n"
        f"FAULT: {fault_type}\n"
        f"TITLE: {title}\n"
        f"SYMPTOMS: {symptoms}\n"
        f"WINDOW_PATTERN: persistence={persistence}, severity={severity}, notes={notes}\n"
        f"ROOT_CAUSE: {root_cause}\n"
        f"VERIFICATION: {verification}\n"
        f"RESOLUTION: {resolution}\n"
        f"EXPECTED_POST_FIX: {expected}\n"
        f"TAGS: {tags}\n"
    ).strip()


def build_case_metadata(case: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "case_id": case.get("case_id"),
        "fault_type": case.get("fault_type"),
        "equipment_scope": case.get("equipment_scope"),
        "tags": join_list(case.get("tags")),
        "confidence": case.get("confidence"),
        "source": "past_case",
    }


def get_chroma_collection(name: str):
    try:
        import chromadb  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency: chromadb. Install with `pip install chromadb`."
        ) from exc

    client = chromadb.PersistentClient(path=str(Path("chroma_db").resolve()))
    embed_fn = HashEmbeddingFunction(dim=1024)
    collection = client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=embed_fn,
    )
    return collection


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cases_path = repo_root / "knowledge" / "past_cases" / "past_cases.jsonl"

    collection = get_chroma_collection("past_cases")

    ids: List[str] = []
    documents: List[str] = []
    metadatas: List[Dict[str, Any]] = []

    with cases_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            if not isinstance(case, dict):
                continue
            case_id = str(case.get("case_id", "")).strip()
            if not case_id:
                continue

            ids.append(case_id)
            documents.append(build_case_embedding_text(case))
            metadatas.append(build_case_metadata(case))

    if ids:
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    print(f"upserted_cases={len(ids)}")
    if documents:
        ex = documents[0].splitlines()[0:6]
        print("example_preview=")
        for ln in ex:
            print("  " + ln)


if __name__ == "__main__":
    main()
