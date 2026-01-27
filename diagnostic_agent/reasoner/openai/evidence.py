from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple


def derive_window_id(w: Any, idx: int) -> str:
    """Derive a stable window ID for prompting/evidence references."""

    wid = getattr(w, "window_id", None)
    if isinstance(wid, str) and wid.strip():
        return wid.strip()

    t = getattr(w, "time", None)
    if isinstance(t, dict):
        st = t.get("start")
        en = t.get("end")
        if isinstance(st, str) and isinstance(en, str) and st and en:
            return f"window:{st}–{en}"

    return f"window:idx:{idx}"


def windows_payload(windows: Sequence[Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Build prompt payload for recent windows and collect allowed evidence IDs."""

    out: List[Dict[str, Any]] = []
    ids: List[str] = []

    recent = list(windows or [])[-8:]
    for idx, w in enumerate(recent):
        wid = derive_window_id(w, idx)
        ids.append(wid)
        out.append(
            {
                "evidence_id": wid,
                "window_id": getattr(w, "window_id", None),
                "time": getattr(w, "time", None),
                "signature": getattr(w, "signature", None),
                "anomalies": getattr(w, "anomalies", None),
                "summary_text": getattr(w, "summary_text", None),
            }
        )

    return out, ids


def docs_payload(docs: Sequence[Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Build prompt payload for retrieved docs and collect allowed chunk IDs."""

    out: List[Dict[str, Any]] = []
    ids: List[str] = []
    docs_list = list(docs or [])

    def _distance(d: Any) -> float:
        v = getattr(d, "distance", None)
        return float(v) if isinstance(v, (int, float)) else 1e9

    docs_list = sorted(docs_list, key=_distance)[:12]
    for d in docs_list:
        corpus = str(getattr(d, "corpus", "") or "")
        chunk_id = str(getattr(d, "doc_id", "") or "")

        meta = getattr(d, "metadata", None)
        meta = meta if isinstance(meta, dict) else {}

        source_doc_id = str(meta.get("doc_id") or meta.get("source_doc_id") or "")
        chunk_type = meta.get("chunk_type")

        pages = None
        ps = meta.get("page_start")
        pe = meta.get("page_end")
        if isinstance(ps, int) or isinstance(pe, int):
            pages = {"start": ps, "end": pe}

        dist = getattr(d, "distance", None)
        text = str(getattr(d, "text", "") or "")
        if len(text) > 1400:
            text = text[:1400] + "…"

        if chunk_id:
            ids.append(chunk_id)

        out.append(
            {
                "corpus": corpus,
                "doc_id": source_doc_id or chunk_id,
                "chunk_id": chunk_id,
                "source": meta.get("file_name")
                or meta.get("title")
                or meta.get("source")
                or None,
                "chunk_type": chunk_type,
                "pages": pages,
                "score": dist,
                "text": text,
            }
        )

    return out, ids


def top_rule_ids(windows: Sequence[Any]) -> List[str]:
    counts: Dict[str, int] = {}
    for w in windows or []:
        anomalies = getattr(w, "anomalies", None)
        if not isinstance(anomalies, list):
            continue
        for a in anomalies:
            if not isinstance(a, dict):
                continue
            rid = str(a.get("rule_id") or "").strip()
            if not rid:
                continue
            counts[rid] = counts.get(rid, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [r for r, _ in ranked][:5]


def symptom_summary(windows: Sequence[Any]) -> str:
    if not windows:
        return ""

    for w in reversed(list(windows)):
        st = getattr(w, "summary_text", None)
        if isinstance(st, str) and st.strip():
            return st.strip()[:500]

    parts: List[str] = []
    for w in list(windows)[-2:]:
        anomalies = getattr(w, "anomalies", None)
        if not isinstance(anomalies, list):
            continue
        for a in anomalies:
            if not isinstance(a, dict):
                continue
            msg = a.get("message") or a.get("symptom") or ""
            msg = str(msg).strip()
            if msg:
                parts.append(msg)

    return "; ".join(parts)[:500]


def overall_time_range(windows: Sequence[Any]) -> Dict[str, str | None]:
    starts: List[str] = []
    ends: List[str] = []

    for w in windows or []:
        t = getattr(w, "time", None)
        if not isinstance(t, dict):
            continue
        st = t.get("start")
        en = t.get("end")
        if isinstance(st, str) and st:
            starts.append(st)
        if isinstance(en, str) and en:
            ends.append(en)

    return {
        "start": min(starts) if starts else None,
        "end": max(ends) if ends else None,
    }
