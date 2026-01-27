from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from diagnostic_agent.controller.schemas import RetrievalStats, RetrievedDoc


@dataclass(frozen=True)
class RetrievalRouterConfig:
    manuals_top_k: int = 5
    past_cases_top_k: int = 5
    case_history_top_k: int = 5


class RetrievalRouter:
    """Hierarchical retrieval router.

    Stage 1: manuals + past_cases (always attempt)
    Stage 2: case_history (conditional; max once)

    This router never raises; it returns empty results + stats.error on failures.
    """

    def __init__(self, cfg: Optional[RetrievalRouterConfig] = None) -> None:
        self.cfg = cfg or RetrievalRouterConfig()

    def stage1(
        self, *, query: str, where: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[RetrievedDoc], RetrievalStats]:
        stats = RetrievalStats()
        docs: List[RetrievedDoc] = []

        try:
            from static_layer.retrievers import retrieve_manuals, retrieve_past_cases

            manuals = retrieve_manuals(
                query=query, top_k=self.cfg.manuals_top_k, where=where
            )
            past = retrieve_past_cases(
                query=query, top_k=self.cfg.past_cases_top_k, where=where
            )

            for r in manuals or []:
                if not isinstance(r, dict):
                    continue
                docs.append(
                    RetrievedDoc(
                        corpus="manuals",
                        doc_id=str(r.get("id") or ""),
                        distance=r.get("score"),
                        text=str(r.get("text_snippet") or ""),
                        metadata=dict(r.get("metadata") or {}),
                    )
                )

            for r in past or []:
                if not isinstance(r, dict):
                    continue
                docs.append(
                    RetrievedDoc(
                        corpus="past_cases",
                        doc_id=str(r.get("id") or ""),
                        distance=r.get("score"),
                        text=str(r.get("text_snippet") or ""),
                        metadata=dict(r.get("metadata") or {}),
                    )
                )

            stats.manuals_count = len([d for d in docs if d.corpus == "manuals"])
            stats.past_cases_count = len([d for d in docs if d.corpus == "past_cases"])
            stats.manuals_has_any = stats.manuals_count > 0
            stats.past_cases_has_any = stats.past_cases_count > 0

            distances = [
                d.distance for d in docs if isinstance(d.distance, (int, float))
            ]
            if distances:
                stats.min_distance = float(min(distances))
                stats.avg_distance = float(sum(distances) / max(len(distances), 1))

        except Exception as exc:
            stats.error = f"stage1_error:{type(exc).__name__}:{exc}"

        return docs, stats

    def stage2_case_history(
        self, *, query: str, where: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[RetrievedDoc], RetrievalStats]:
        stats = RetrievalStats()
        docs: List[RetrievedDoc] = []

        try:
            # Dynamic layer has a helper for other collections; we add a direct call here.
            from dynamic_layer.retrievers import _get_collection  # type: ignore

            col = _get_collection(collection_name="case_history")
            raw = col.query(
                query_texts=[query],
                n_results=self.cfg.case_history_top_k,
                where=where,
                include=["documents", "metadatas", "distances"],
            )

            ids = (raw.get("ids") or [[]])[0]
            documents = (raw.get("documents") or [[]])[0]
            metas = (raw.get("metadatas") or [[]])[0]
            distances = (raw.get("distances") or [[]])[0]

            for i, _id in enumerate(ids):
                docs.append(
                    RetrievedDoc(
                        corpus="case_history",
                        doc_id=str(_id),
                        distance=distances[i] if i < len(distances) else None,
                        text=str(documents[i] if i < len(documents) else ""),
                        metadata=dict(metas[i] if i < len(metas) else {}),
                    )
                )

            stats.case_history_count = len(docs)
            distances = [
                d.distance for d in docs if isinstance(d.distance, (int, float))
            ]
            if distances:
                stats.min_distance = float(min(distances))
                stats.avg_distance = float(sum(distances) / max(len(distances), 1))

        except Exception as exc:
            stats.error = f"stage2_error:{type(exc).__name__}:{exc}"

        return docs, stats


def build_retrieval_query(
    *,
    detected_fault_type: str,
    rule_ids: List[str],
    symptom_summary: str,
) -> str:
    rid = ", ".join([r for r in rule_ids if r][:5])
    parts = [
        f"fault_type={detected_fault_type}",
        f"rules={rid}" if rid else "",
        symptom_summary.strip(),
    ]
    return "\n".join([p for p in parts if p]).strip()
