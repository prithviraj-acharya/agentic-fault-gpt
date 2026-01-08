"""Phase 4: Build Chroma collection `manuals` from local PDF manuals.

- Reads: knowledge/metadata/documents_metadata.json
- Iterates PDFs under: knowledge/manual/
- Extracts text, cleans, chunks, and upserts into persistent Chroma DB at ./chroma_db

Deterministic manual chunk IDs:
  {doc_id}::chunk::{chunk_index}

This script is idempotent: re-running upserts the same IDs (no duplicates).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, cast

# Load environment variables for OpenAI
from dotenv import load_dotenv

load_dotenv()

# Use OpenAI embedding function
from openai_embedder import OpenAIEmbeddingFunction

# --------- PDF extraction ---------


def extract_pdf_pages_text(pdf_path: Path) -> List[str]:
    """Extract per-page text from a PDF.

    Requires `pypdf`.
    """

    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency: pypdf. Install with `pip install pypdf`."
        ) from exc

    reader = PdfReader(str(pdf_path))
    pages_text: List[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages_text.append(text)
    return pages_text


def remove_repeated_headers_footers(pages_text: List[str]) -> str:
    """Remove highly repeated short lines across pages (headers/footers)."""

    # Count line frequency by page (unique lines per page).
    freq: Dict[str, int] = {}
    for page_text in pages_text:
        lines = [ln.strip() for ln in page_text.splitlines()]
        unique = set(ln for ln in lines if ln)
        for ln in unique:
            if 0 < len(ln) <= 80:
                freq[ln] = freq.get(ln, 0) + 1

    n_pages = max(1, len(pages_text))
    # Lines that appear on >= 50% of pages are likely headers/footers.
    repeated = {ln for ln, c in freq.items() if c / n_pages >= 0.5}

    cleaned_pages: List[str] = []
    for page_text in pages_text:
        out_lines: List[str] = []
        for ln in page_text.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s in repeated:
                continue
            # Drop standalone page numbers.
            if re.fullmatch(r"\d{1,4}", s):
                continue
            out_lines.append(s)
        cleaned_pages.append("\n".join(out_lines))

    # Join pages with a hard separator so headings detection isn't confused.
    return "\n\n".join(cleaned_pages)


def remove_repeated_headers_footers_pages(pages_text: List[str]) -> List[str]:
    """Like remove_repeated_headers_footers(), but returns a list of cleaned pages.

    This lets us preserve page boundaries so we can attach (page_start, page_end)
    to each chunk for citation.
    """

    freq: Dict[str, int] = {}
    for page_text in pages_text:
        lines = [ln.strip() for ln in page_text.splitlines()]
        unique = set(ln for ln in lines if ln)
        for ln in unique:
            if 0 < len(ln) <= 80:
                freq[ln] = freq.get(ln, 0) + 1

    n_pages = max(1, len(pages_text))
    repeated = {ln for ln, c in freq.items() if c / n_pages >= 0.5}

    cleaned_pages: List[str] = []
    for page_text in pages_text:
        out_lines: List[str] = []
        for ln in page_text.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s in repeated:
                continue
            if re.fullmatch(r"\d{1,4}", s):
                continue
            out_lines.append(s)
        cleaned_pages.append("\n".join(out_lines))

    return cleaned_pages


def normalize_whitespace(text: str) -> str:
    text = text.replace("\u00a0", " ")
    # Collapse excessive whitespace but preserve newlines for heading detection.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --------- Chunking ---------


def estimate_tokens(text: str) -> int:
    # Approximate tokens as ~ words * 1.3
    words = len(re.findall(r"\S+", text))
    return int(words * 1.3)


def tokens_to_words(tokens: int) -> int:
    # Inverse approximation for windowing by words.
    return max(50, int(tokens / 1.3))


def is_heading_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if len(s) > 120:
        return False

    # Numbered heading patterns: 1, 1.2, 2.3.4
    if re.match(r"^\d+(\.\d+){0,4}[\).:-]?\s+\S+", s):
        return True

    # "SECTION 3" / "CHAPTER" / "APPENDIX"
    if re.match(r"^(section|chapter|appendix)\s+\w+", s.lower()):
        return True

    # ALL CAPS-ish short lines
    letters = [c for c in s if c.isalpha()]
    if letters:
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper_ratio >= 0.7 and len(s.split()) <= 12:
            return True

    # Title-case short lines with few punctuation
    if len(s.split()) <= 10 and re.fullmatch(r"[A-Za-z0-9 ,:/()\-]+", s):
        # heuristic: lots of words start uppercase
        words = [w for w in s.split() if w]
        if words:
            cap = sum(1 for w in words if w[:1].isupper())
            if cap / len(words) >= 0.7:
                return True

    return False


@dataclass
class Section:
    heading: str
    body: str


def split_into_sections(text: str) -> List[Section]:
    lines = [ln.rstrip() for ln in text.splitlines()]

    # Build sections by heading detection.
    sections: List[Section] = []
    current_heading = ""
    current_body_lines: List[str] = []

    found_any_heading = False

    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if is_heading_line(s):
            found_any_heading = True
            if current_body_lines:
                sections.append(
                    Section(
                        heading=current_heading,
                        body="\n".join(current_body_lines).strip(),
                    )
                )
            current_heading = s
            current_body_lines = []
        else:
            current_body_lines.append(s)

    if current_body_lines:
        sections.append(
            Section(heading=current_heading, body="\n".join(current_body_lines).strip())
        )

    # If no reliable headings, return a single section.
    if not found_any_heading:
        return [Section(heading="", body=text.strip())]

    # Filter empty bodies.
    out = [sec for sec in sections if sec.body.strip()]
    return out or [Section(heading="", body=text.strip())]


def infer_chunk_type(heading: str, chunk_text: str) -> str:
    h = (heading or "").lower()
    t = (chunk_text or "").lower()

    if "table of contents" in h or re.fullmatch(r"contents", h.strip()):
        return "toc"
    if "contents" in h and len(h.split()) <= 3:
        return "toc"

    if "table" in h and "fault" in h:
        return "fault_table"
    if "fault" in h and "table" in t:
        return "fault_table"

    if "procedure" in h or "steps" in h or "startup" in h or "shutdown" in h:
        return "procedure"
    if "checklist" in h or "check list" in h:
        return "checklist"
    if "definition" in h or "glossary" in h:
        return "definition"
    if "equation" in h or "formula" in h:
        return "equation"
    if "example" in h or "case" in h:
        return "case_example"

    # Weak content-based hints
    if re.search(r"\bprocedure\b", t) and re.search(r"\bstep\b", t):
        return "procedure"

    return "general_section"


def fixed_chunk_words(text: str, chunk_tokens: int, overlap_tokens: int) -> List[str]:
    words = re.findall(r"\S+", text)
    if not words:
        return []

    chunk_size = tokens_to_words(chunk_tokens)
    overlap = min(chunk_size - 1, tokens_to_words(overlap_tokens))
    stride = max(1, chunk_size - overlap)

    chunks: List[str] = []
    i = 0
    while i < len(words):
        window = words[i : i + chunk_size]
        chunk = " ".join(window).strip()
        if chunk:
            chunks.append(chunk)
        if i + chunk_size >= len(words):
            break
        i += stride

    return chunks


def chunk_manual_text(
    text: str,
    chunk_tokens: int,
    overlap_tokens: int,
) -> List[Tuple[str, str]]:
    """Return list of (chunk_text, chunk_type)."""

    sections = split_into_sections(text)
    chunks: List[Tuple[str, str]] = []

    for sec in sections:
        sec_text = sec.body.strip()
        if sec.heading.strip():
            combined = f"{sec.heading.strip()}\n{sec_text}".strip()
        else:
            combined = sec_text

        # If section is already small enough, keep as one chunk.
        if estimate_tokens(combined) <= chunk_tokens:
            ctype = infer_chunk_type(sec.heading, combined)
            chunks.append((combined, ctype))
            continue

        # Otherwise break it down by fixed chunking.
        subchunks = fixed_chunk_words(
            combined, chunk_tokens=chunk_tokens, overlap_tokens=overlap_tokens
        )
        for sub in subchunks:
            ctype = infer_chunk_type(sec.heading, sub)
            chunks.append((sub, ctype))

    # Final pass: drop extremely tiny chunks.
    chunks = [(t, ct) for (t, ct) in chunks if len(t.split()) >= 30]
    return chunks


# --------- Metadata helpers ---------


def join_list(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "|".join(str(x) for x in value)
    return str(value)


def build_manual_chunk_metadata(
    doc_meta: Dict[str, Any],
    chunk_index: int,
    chunk_type: str,
    *,
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
) -> Dict[str, Any]:
    # Required fields from prompt.
    return {
        "doc_id": doc_meta.get("doc_id"),
        "file_name": doc_meta.get("file_name"),
        "authority": doc_meta.get("authority"),
        "doc_type": doc_meta.get("doc_type"),
        "ui_label": doc_meta.get("ui_label"),
        "citation_short": doc_meta.get("citation_short"),
        "supports_diagnosis": bool(doc_meta.get("supports_diagnosis", False)),
        "supports_resolution": bool(doc_meta.get("supports_resolution", False)),
        "reasoning_role": join_list(doc_meta.get("reasoning_role")),
        "equipment_scope": join_list(doc_meta.get("equipment_scope")),
        "fault_types": join_list(doc_meta.get("fault_types")),
        "canonical_topics": join_list(doc_meta.get("canonical_topics")),
        "chunk_index": int(chunk_index),
        "chunk_type": chunk_type,
        "page_start": page_start,
        "page_end": page_end,
        "source": "manual",
    }


def _normalize_ws_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _build_page_corpus(cleaned_pages: List[str]) -> Tuple[str, List[Tuple[int, int]]]:
    """Return (corpus, page_spans).

    corpus is all pages joined by single spaces after whitespace normalization.
    page_spans is a list of (start, end) char offsets into corpus for each page.
    """

    norm_pages = [_normalize_ws_for_match(p) for p in cleaned_pages]
    spans: List[Tuple[int, int]] = []
    cursor = 0
    parts: List[str] = []
    for p in norm_pages:
        if parts:
            cursor += 1  # join-space
        start = cursor
        parts.append(p)
        cursor += len(p)
        end = cursor
        spans.append((start, end))
    corpus = " ".join(parts)
    return corpus, spans


def _span_to_page_range(
    span: Tuple[int, int], page_spans: List[Tuple[int, int]]
) -> Tuple[Optional[int], Optional[int]]:
    s, e = span
    if s < 0 or e <= 0 or e <= s:
        return None, None

    first: Optional[int] = None
    last: Optional[int] = None
    for i, (ps, pe) in enumerate(page_spans):
        if pe <= s:
            continue
        if ps >= e:
            break
        if first is None:
            first = i + 1  # 1-based pages
        last = i + 1
    return first, last


def load_documents_metadata(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("documents_metadata.json must be a list")
    return [d for d in data if isinstance(d, dict)]


def get_chunk_params(doc_meta: Dict[str, Any]) -> Tuple[int, int]:
    # Respect per-doc recommendations when present.
    size = doc_meta.get("recommended_chunk_size_tokens")
    overlap = doc_meta.get("recommended_overlap_tokens")

    try:
        size_i = int(size) if size is not None else 800
    except Exception:
        size_i = 800

    try:
        overlap_i = int(overlap) if overlap is not None else 100
    except Exception:
        overlap_i = 100

    # Safety bounds
    size_i = max(300, min(2000, size_i))
    overlap_i = max(0, min(size_i - 1, overlap_i))
    return size_i, overlap_i


# --------- Chroma integration ---------


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


def upsert_manual_chunks(
    collection,
    doc_id: str,
    chunks: List[Tuple[str, str]],
    doc_meta: Dict[str, Any],
    *,
    page_corpus: str,
    page_spans: List[Tuple[int, int]],
) -> None:
    ids: List[str] = []
    documents: List[str] = []
    metadatas: List[Dict[str, Any]] = []

    for idx, (chunk_text, chunk_type) in enumerate(chunks):
        chunk_norm = _normalize_ws_for_match(chunk_text)
        pos = page_corpus.find(chunk_norm) if chunk_norm else -1
        if pos >= 0:
            ps, pe = _span_to_page_range((pos, pos + len(chunk_norm)), page_spans)
        else:
            ps, pe = None, None

        chunk_id = f"{doc_id}::chunk::{idx}"
        ids.append(chunk_id)
        documents.append(chunk_text)
        metadatas.append(
            build_manual_chunk_metadata(
                doc_meta,
                chunk_index=idx,
                chunk_type=chunk_type,
                page_start=ps,
                page_end=pe,
            )
        )

    # Batch upsert.
    if ids:
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    meta_path = repo_root / "knowledge" / "metadata" / "documents_metadata.json"
    manuals_dir = repo_root / "knowledge" / "manual"

    docs_meta = load_documents_metadata(meta_path)
    manuals = get_chroma_collection("manuals")

    # Map file_name -> doc_meta for convenience.
    meta_by_file = {d.get("file_name"): d for d in docs_meta}

    pdf_paths = sorted(manuals_dir.glob("*.pdf"))
    if not pdf_paths:
        raise RuntimeError(f"No PDFs found in {manuals_dir}")

    for pdf_path in pdf_paths:
        file_name = pdf_path.name
        doc_meta = meta_by_file.get(file_name)
        if not doc_meta:
            # Skip PDFs not present in metadata (keep strict provenance).
            print(f"[SKIP] {file_name} (no metadata entry)")
            continue

        doc_id = str(doc_meta.get("doc_id"))
        chunk_tokens, overlap_tokens = get_chunk_params(doc_meta)

        pages_text = extract_pdf_pages_text(pdf_path)
        cleaned_pages = [
            normalize_whitespace(p)
            for p in remove_repeated_headers_footers_pages(pages_text)
        ]
        cleaned = normalize_whitespace("\n\n".join(cleaned_pages))

        page_corpus, page_spans = _build_page_corpus(cleaned_pages)

        chunks = chunk_manual_text(
            cleaned, chunk_tokens=chunk_tokens, overlap_tokens=overlap_tokens
        )
        upsert_manual_chunks(
            manuals,
            doc_id=doc_id,
            chunks=chunks,
            doc_meta=doc_meta,
            page_corpus=page_corpus,
            page_spans=page_spans,
        )

        preview = (
            chunks[0][0][:220].replace("\n", " ")
            + ("..." if len(chunks[0][0]) > 220 else "")
            if chunks
            else "(no chunks)"
        )
        print(f"doc_id={doc_id} chunks={len(chunks)} preview={preview}")


if __name__ == "__main__":
    main()
