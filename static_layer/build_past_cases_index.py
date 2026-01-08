"""Phase 4: Build Chroma collection `past_cases` from local JSONL past cases.

- Reads: knowledge/past_cases/past_cases.jsonl
- Creates embedding text per case (prompt-specified format)
- Upserts into persistent Chroma DB at ./chroma_db, collection `past_cases`

Deterministic IDs:
  past case id == case_id

This script is idempotent: re-running upserts the same IDs (no duplicates).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

# Load environment variables for OpenAI
from dotenv import load_dotenv

load_dotenv()

# Use OpenAI embedding function (works for both module/script execution)
try:
    # Preferred: supports `python -m static_layer.build_past_cases_index`
    from static_layer.openai_embedder import OpenAIEmbeddingFunction
except Exception:  # pragma: no cover
    # Fallback: supports `python -m build_past_cases_index` from within static_layer
    from openai_embedder import OpenAIEmbeddingFunction


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
    embed_fn = OpenAIEmbeddingFunction()
    collection = client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=cast(Any, embed_fn),
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
