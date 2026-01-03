from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from collections import Counter

from pypdf import PdfReader


SCHEMA_VERSION = "1.0"

DOC_TYPE_ALLOWED = {
    "guideline",
    "research",
    "oem_manual",
    "iom",
    "troubleshooting_guide",
    "handbook",
    "assessment_guidelines",
    "survey_report",
    "other",
}

EQUIPMENT_SCOPE_ALLOWED = {
    "AHU",
    "VAV",
    "chiller",
    "cooling_coil",
    "mixing_box",
    "damper",
    "fan",
    "sensor",
    "controller",
    "building_systems",
    "general_hvac",
}

FAULT_TYPES_ALLOWED = {
    "cooling_inefficiency",
    "stuck_damper",
    "sensor_drift",
    "sensor_failure",
    "economizer_fault",
    "coil_fouling",
    "valve_fault",
    "airflow_fault",
    "leakage",
    "general_fdd",
}

CANONICAL_TOPICS_ALLOWED = {
    "economizer",
    "mixed_air",
    "cooling_coil",
    "dampers",
    "valves",
    "sensors",
    "controls_sequences",
    "maintenance",
    "commissioning",
    "fault_detection",
    "diagnostics",
    "energy_efficiency",
}

REASONING_ROLE_ALLOWED = {
    "fault_condition_definition",
    "possible_cause_enumeration",
    "physical_behavior_explanation",
    "diagnostic_tests",
    "inspection_procedure",
    "resolution_steps",
    "maintenance_checklist",
    "evaluation_methodology",
}

PREFERRED_CHUNK_TYPES_ALLOWED = {
    "toc",
    "fault_table",
    "procedure",
    "checklist",
    "definition",
    "equation",
    "case_example",
    "general_section",
}

CHUNKING_STRATEGY_ALLOWED = {"section_based", "fixed_tokens", "hybrid"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


MONTHS = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
}


def looks_like_doc_code(line: str) -> bool:
    # Examples: CLCH-SVX010E-EN, Form 102.20-OM2, EN7499511-08
    l = line.strip()
    if len(l) < 6:
        return False
    # Many digits + hyphens/periods and few spaces
    if l.count(" ") <= 1 and re.search(r"[A-Za-z].*\d|\d.*[A-Za-z]", l) and re.search(r"[-._]", l):
        # If it's mostly alnum + -._
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._\-]{4,}", l):
            return True
    if re.search(r"\b(form|document|model|bulletin)\b\s*\d", l, flags=re.IGNORECASE):
        return True
    if re.fullmatch(r"[A-Z]{2,}\d{4,}[A-Z0-9\-._]*", l):
        return True
    return False


def is_boilerplate_line(line: str) -> bool:
    l = normalize_ws(line)
    if not l:
        return True

    low = l.lower()

    # Obvious non-content
    if low in {"foreword", "disclaimer", "copyright", "acknowledgments", "acknowledgements"}:
        return True
    if "issue date" in low or "printed" in low:
        return True
    if "prepared by" in low or "prepared for" in low:
        return True
    if re.search(r"\bdoe\b|\bgo-\d{6,}\b|\bdoe/\w+\b", low):
        return True
    if "lawrence berkeley" in low:
        return True
    if "all rights reserved" in low or "©" in l or "copyright" in low:
        return True
    if re.search(r"\bissn\b|\bcoden\b|\bisbn\b", low):
        return True
    if re.search(r"\bstandards\s+committee\b|\bproject\s+committee\b", low):
        return True
    if re.search(r"\bvolume\b\s*\d+|\bnumber\b\s*\d+", low):
        return True
    # Journal/page header patterns that are not navigable sections
    if re.fullmatch(r"\d+\s+hvac&r\s+research", low):
        return True
    if "hvac&r research" in low and len(low.split()) <= 6 and re.search(r"\b\d+\b", low):
        return True
    if any(m in low for m in MONTHS) and re.search(r"\b(19\d{2}|20\d{2})\b", low):
        return True
    if looks_like_doc_code(l):
        return True
    if "error! reference source not found" in low:
        return True

    # Mostly numeric / math-like snippets are poor retrieval queries
    alpha = sum(ch.isalpha() for ch in l)
    digits = sum(ch.isdigit() for ch in l)
    if alpha <= 2 and digits >= 2:
        return True
    if re.search(r"[=<>±×∙•⁄∕]", l) and alpha < 8:
        return True
    # Many equation-like delimiters with few letters
    if re.search(r"[()\[\]{}+/]", l) and alpha < 8:
        return True
    # Variable/parameter-like tokens (e.g., "2 a6Tra", "3 a13Tamb") are not navigable sections.
    if re.match(r"^\d+\s+[a-z]\d+[a-z]{1,6}\b", low):
        return True
    if len(l) <= 3:
        return True

    return False


def clean_heading_candidate(line: str) -> str | None:
    l = normalize_ws(line)
    if not l:
        return None

    # Trim common leader artifacts
    l = l.strip("-•·")
    l = normalize_ws(l)

    # Normalize common corrupted casing for SECTION/CHAPTER labels (PDF extraction artifacts)
    l = re.sub(r"^secti\s*on\b", "SECTION", l, flags=re.IGNORECASE)
    l = re.sub(r"^chapter\b", "CHAPTER", l, flags=re.IGNORECASE)
    if is_boilerplate_line(l):
        return None

    # Exclude overly-long lines (likely body text) unless clearly a numbered heading
    if len(l) > 90 or len(l.split()) > 12:
        if not re.match(r"^(\d+(\.\d+)*)(\s+|\s*[-:])\S+", l):
            return None

    # Exclude short variable-like headings with low alphabetic content
    alpha = sum(ch.isalpha() for ch in l)
    digits = sum(ch.isdigit() for ch in l)
    if alpha < 4 and digits >= 1:
        return None

    return l


def extract_text_pages(reader: PdfReader, max_pages: int) -> list[str]:
    pages_text: list[str] = []
    for i, page in enumerate(reader.pages[:max_pages]):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages_text.append(text)
    return pages_text


def flatten_pdf_outline(reader: PdfReader) -> list[str]:
    # Use embedded PDF bookmarks/outlines as evidence-grounded section titles.
    # Not all PDFs have outlines; extraction can fail.
    titles: list[str] = []

    def walk(node: object) -> None:
        if node is None:
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        # pypdf outline items often have .title
        title = getattr(node, "title", None)
        if isinstance(title, str):
            tt = normalize_ws(title)
            if tt:
                titles.append(tt)
        # Some nodes may be dict-like
        if isinstance(node, dict):
            t = node.get("/Title")
            if isinstance(t, str):
                tt = normalize_ws(t)
                if tt:
                    titles.append(tt)
            kids = node.get("/First") or node.get("/Kids")
            if kids is not None:
                walk(kids)

    try:
        walk(getattr(reader, "outline", None))
    except Exception:
        return []

    # De-duplicate, preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for t in titles:
        tl = t.lower()
        if tl in seen:
            continue
        seen.add(tl)
        uniq.append(t)
    return uniq


def find_publication_year(text: str) -> int | None:
    # Conservative: only accept explicit 4-digit years 19xx/20xx.
    years = re.findall(r"\b(19\d{2}|20\d{2})\b", text)
    if not years:
        return None
    # If multiple years, do not guess which is publication; leave null.
    uniq = sorted({int(y) for y in years})
    if len(uniq) == 1:
        return uniq[0]
    return None


def find_version_or_revision(text: str) -> str | None:
    # Evidence-based: require explicit marker + a non-generic identifier.
    # Avoid picking up words like "revisions" or "revision or".
    patterns: list[tuple[str, str]] = [
        (r"\bRevision\s*[:#]\s*([A-Za-z0-9][A-Za-z0-9._\-/]{0,40})\b", "Revision"),
        (r"\bRev\.?\s*[:#]\s*([A-Za-z0-9][A-Za-z0-9._\-/]{0,40})\b", "Rev"),
        (r"\bVersion\s*[:#]\s*([A-Za-z0-9][A-Za-z0-9._\-/]{0,40})\b", "Version"),
    ]
    for pat, label in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            token = normalize_ws(m.group(1))
            # Token must include at least one digit OR be multi-part (e.g., "A-01").
            if re.search(r"\d", token) or re.search(r"[-._/]", token):
                return f"{label}: {token}"

    # Only accept explicit issue/print date markers when labeled.
    labeled_date = re.search(
        r"\b(Issue\s+Date|Issued|Publication\s+Date|Printed)\s*[:#]\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}[/-]\d{4}|\d{4}[/-]\d{2}[/-]\d{2})\b",
        text,
        flags=re.IGNORECASE,
    )
    if labeled_date:
        return normalize_ws(labeled_date.group(0))

    return None


def guess_language(text: str) -> str | None:
    # Minimal: if there are enough ASCII letters and common English words.
    t = text.lower()
    if any(w in t for w in ["the ", "and ", "installation", "operation", "contents", "chapter"]):
        return "en"
    return None


def extract_heading_lines(pages_text: list[str], max_pages: int = 15) -> list[str]:
    # Evidence-based fallback when TOC/outlines are missing.
    # Heuristics: all-caps lines, numbered headings, and Chapter/Section markers.
    headings: list[str] = []
    for page in pages_text[:max_pages]:
        for raw in page.splitlines():
            line = clean_heading_candidate(raw)
            if not line:
                continue

            is_numbered = bool(re.match(r"^(\d+(\.\d+)*)(\s+|\s*[-:])\S+", line))
            is_chapter = bool(re.match(r"^(chapter\s+\d+|section\s+\d+)\b", line, flags=re.IGNORECASE))
            # All-caps heading (allow punctuation and digits)
            caps_letters = re.sub(r"[^A-Za-z]", "", line)
            is_all_caps = bool(caps_letters) and caps_letters.upper() == caps_letters and len(caps_letters) >= 8

            if is_all_caps or is_numbered or is_chapter:
                headings.append(line)

    # De-duplicate preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for h in headings:
        hl = h.lower()
        if hl in seen:
            continue
        seen.add(hl)
        uniq.append(h)
    return uniq


def extract_title(reader: PdfReader, first_pages_text: list[str]) -> tuple[str | None, str | None]:
    # Prefer PDF metadata title if present.
    meta = getattr(reader, "metadata", None)
    if meta:
        t = getattr(meta, "title", None)
        if t:
            tt = normalize_ws(str(t))
            if tt and tt.lower() not in {"untitled", ""}:
                return tt, "Used PDF metadata title."

    # Conservative heuristic from first page lines: take the first non-empty line
    # that is not purely a page number / header.
    first = first_pages_text[0] if first_pages_text else ""
    lines = [normalize_ws(l) for l in first.splitlines()]
    lines = [l for l in lines if l]

    junk = re.compile(r"^(page\s+\d+|\d+)$", re.IGNORECASE)
    for line in lines[:20]:
        if junk.match(line):
            continue
        # Avoid grabbing generic headers
        if line.lower() in {"contents", "table of contents"}:
            continue
        if len(line) >= 6:
            return line, "Heuristic: first substantive line on page 1."

    return None, "Unable to confidently identify title from PDF metadata or page 1 text."


def extract_authority(first_pages_text: list[str]) -> tuple[str | None, str | None]:
    # Very conservative: authority must appear explicitly as a short proper name.
    # We only accept if it appears as a prominent standalone token on page 1/2.
    blob = "\n".join(first_pages_text[:2])
    blob_norm = "\n".join(normalize_ws(l) for l in blob.splitlines() if normalize_ws(l))

    # Common authority markers found in docs (still evidence-based: requires exact substring)
    candidates = [
        "ASHRAE",
        "NIST",
        "NREL",
        "Honeywell",
        "PNNL",
        "York",
        "Johnson Controls",
        "Trane",
        "Carrier",
    ]
    for c in candidates:
        if c.lower() in blob_norm.lower():
            return c, f"Found explicit organization string '{c}' in first pages text."

    return None, "No explicit publisher/organization string confidently found on first pages."


def detect_doc_type(first_pages_text: list[str], pdf_metadata_title: str | None) -> tuple[str, str]:
    # Evidence-only: classify based on explicit self-identification in extracted PDF text.
    # Avoid using filenames as that is not PDF content.
    # Use early pages (still local PDF text) so we don't miss explicit labels that
    # appear on the cover verso or early front matter.
    early_text = "\n".join(first_pages_text[:15])
    meta_title = (pdf_metadata_title or "").strip()
    t = (early_text + "\n" + meta_title).lower()

    # IOM: explicit identification.
    if re.search(r"installation\s+(and|&)\s+operation\s+manual", t):
        return "iom", "Found explicit 'Installation and Operation Manual' text."
    if re.search(r"installation\s*,\s*operation\s*,\s*(and\s*)?maintenance\s+manual", t):
        return "iom", "Found explicit 'Installation, Operation, and Maintenance Manual' text."
    if re.search(r"operation\s+and\s+maintenance\s+manual", t):
        return "iom", "Found explicit 'Operation and Maintenance Manual' text."
    # Accept IOM abbreviation only when clearly tied to manual context.
    if re.search(r"\bIOM\b.{0,120}\bmanual\b", early_text, flags=re.IGNORECASE) or re.search(
        r"\bmanual\b.{0,120}\bIOM\b", early_text, flags=re.IGNORECASE
    ):
        return "iom", "Found 'IOM' abbreviation in close proximity to 'manual'."

    # Guideline
    if re.search(r"\bguideline\b", t):
        return "guideline", "Found explicit 'Guideline' text."

    # Assessment guidelines
    if "assessment guidelines" in t:
        return "assessment_guidelines", "Found explicit 'Assessment Guidelines' text."

    # Survey report
    if "survey report" in t:
        return "survey_report", "Found explicit 'Survey Report' text."

    # Troubleshooting guide (explicit)
    if "troubleshooting guide" in t:
        return "troubleshooting_guide", "Found explicit 'Troubleshooting Guide' text."

    # Handbook
    if re.search(r"\bhandbook\b", t):
        return "handbook", "Found explicit 'Handbook' text."

    # Research indicators (explicit)
    if "technical note" in t or ("tn" in t and "nist" in t):
        return "research", "Found explicit technical note / research indicator text."
    if "national laboratory" in t or "technical report" in t:
        return "research", "Found explicit technical report / laboratory indicator text."
    # Journal/paper indicators (explicit, not inferred):
    if re.search(r"\babstract\b", t) and re.search(r"\bkeywords\b", t):
        return "research", "Found explicit 'Abstract' and 'Keywords' sections (paper-style)."
    if re.search(r"\bhvac&r\s+research\b", t) or re.search(r"\bjournal\b", t):
        return "research", "Found explicit journal/research publication indicator text."

    # OEM manual (explicit manual wording). This is a fallback when the doc identifies as a manual,
    # but does not explicitly identify as IOM.
    if re.search(r"\bmanual\b", t):
        return "oem_manual", "Found explicit 'Manual' text (not explicitly IOM)."

    return "other", "No explicit self-identification matched allowed doc_type categories."


def extract_key_sections(reader: PdfReader, first_pages_text: list[str]) -> tuple[list[str], str | None]:
    # Try to find a TOC/Contents page in first 12 pages text, then extract lines
    # with dotted leaders or trailing page numbers.
    joined = [p for p in first_pages_text if p]
    if not joined:
        return [], "No extractable text found in scanned/empty first pages."

    for i, page in enumerate(joined[:30]):
        if re.search(r"\b(table of contents|contents)\b", page, flags=re.IGNORECASE):
            # TOC often spans multiple pages; include up to 3 pages starting here.
            toc_blob = "\n".join(joined[i : i + 3])
            lines = [normalize_ws(l) for l in toc_blob.splitlines()]
            lines = [l for l in lines if l]

            sections: list[str] = []
            for line in lines:
                cleaned = clean_heading_candidate(line)
                if not cleaned:
                    continue
                # Filter out sentence-like body text that sometimes appears on the TOC page.
                if re.match(r"^(if|when|then|note)\b", cleaned, flags=re.IGNORECASE):
                    continue
                if len(cleaned.split()) > 14:
                    continue
                # Dotted leaders (common)
                if re.search(r"\.{2,}\s*\d+\s*$", cleaned):
                    title = re.sub(r"\.{2,}\s*\d+\s*$", "", cleaned).strip()
                    if title and len(title) > 3:
                        tclean = clean_heading_candidate(title)
                        if tclean:
                            sections.append(tclean)
                    continue
                # Trailing page numbers
                if re.search(r"\s\d+\s*$", cleaned) and len(cleaned) > 8:
                    title = re.sub(r"\s\d+\s*$", "", cleaned).strip()
                    if title and len(title) > 3:
                        tclean = clean_heading_candidate(title)
                        if tclean:
                            sections.append(tclean)
                    continue
                # Chapter-style headings without page numbers (still headings)
                if re.match(r"^(chapter\s+\d+|section\s+\d+)\b", cleaned, flags=re.IGNORECASE):
                    sections.append(cleaned)

            # De-duplicate while preserving order
            seen: set[str] = set()
            uniq: list[str] = []
            for s in sections:
                if s not in seen:
                    seen.add(s)
                    uniq.append(s)

            if uniq:
                return uniq[:10], "Extracted from a detected Contents/TOC page (up to 3 pages)."

            return [], "Detected a Contents/TOC page but could not reliably parse section lines across TOC pages."

    outline = flatten_pdf_outline(reader)
    if outline:
        cleaned_outline = []
        for t in outline:
            c = clean_heading_candidate(t)
            if c:
                cleaned_outline.append(c)
        if cleaned_outline:
            return cleaned_outline[:10], "No TOC detected; used embedded PDF outline/bookmarks for section titles."

    headings = extract_heading_lines(first_pages_text, max_pages=15)
    if headings:
        return headings[:10], "No TOC/outline detected; used heading-like lines extracted from early pages."

    return [], "No Contents/TOC page detected, no embedded PDF outline/bookmarks, and no reliable headings extracted from early pages."


def evidence_tags(text: str) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    # Evidence-only: only tag when the exact keyword appears in text.
    t = text.lower()

    equipment: list[str] = []
    if re.search(r"\bAHU\b", text) or "air handling unit" in t or "air-handling unit" in t:
        equipment.append("AHU")
    if re.search(r"\bVAV\b", text) or "variable air volume" in t:
        equipment.append("VAV")
    if "chiller" in t:
        equipment.append("chiller")
    if "cooling coil" in t:
        equipment.append("cooling_coil")
    if "mixing box" in t:
        equipment.append("mixing_box")
    if "damper" in t:
        equipment.append("damper")
    if "fan" in t:
        equipment.append("fan")
    if "sensor" in t:
        equipment.append("sensor")
    if "controller" in t:
        equipment.append("controller")
    if "building systems" in t or "building system" in t:
        equipment.append("building_systems")
    if "hvac" in t:
        equipment.append("general_hvac")

    fault_types: list[str] = []
    if "economizer fault" in t or "economiser fault" in t:
        fault_types.append("economizer_fault")
    if "stuck damper" in t:
        fault_types.append("stuck_damper")
    if "sensor drift" in t:
        fault_types.append("sensor_drift")
    if "sensor failure" in t:
        fault_types.append("sensor_failure")
    if "coil fouling" in t or "fouled coil" in t:
        fault_types.append("coil_fouling")
    if "valve fault" in t:
        fault_types.append("valve_fault")
    if "airflow fault" in t:
        fault_types.append("airflow_fault")
    if "leakage" in t:
        fault_types.append("leakage")
    if "fault detection" in t or "fault detection and diagnostics" in t or "fdd" in t:
        fault_types.append("general_fdd")
    if "cooling inefficiency" in t:
        fault_types.append("cooling_inefficiency")

    topics: list[str] = []
    if "economizer" in t or "economiser" in t:
        topics.append("economizer")
    if "mixed air" in t or "mixed-air" in t:
        topics.append("mixed_air")
    if "cooling coil" in t:
        topics.append("cooling_coil")
    if "damper" in t or "dampers" in t:
        topics.append("dampers")
    if "valve" in t or "valves" in t:
        topics.append("valves")
    if "sensor" in t or "sensors" in t:
        topics.append("sensors")
    if "sequence of operations" in t or "sequence of operation" in t or "control sequence" in t:
        topics.append("controls_sequences")
    if "maintenance" in t:
        topics.append("maintenance")
    if "commissioning" in t:
        topics.append("commissioning")
    if "fault detection" in t or "fault detection and diagnostics" in t:
        topics.append("fault_detection")
    if "diagnostic" in t or "diagnostics" in t:
        topics.append("diagnostics")
    if "energy efficiency" in t:
        topics.append("energy_efficiency")

    reasoning_role: list[str] = []
    if "definition" in t or "definitions" in t:
        reasoning_role.append("fault_condition_definition")
    if "possible cause" in t or "causes" in t:
        reasoning_role.append("possible_cause_enumeration")
    if "physical" in t or "thermodynamic" in t:
        reasoning_role.append("physical_behavior_explanation")
    if "test" in t or "diagnostic test" in t:
        reasoning_role.append("diagnostic_tests")
    if "inspection" in t or "inspect" in t:
        reasoning_role.append("inspection_procedure")
    if "corrective action" in t or "repair" in t or "resolve" in t:
        reasoning_role.append("resolution_steps")
    if "checklist" in t:
        reasoning_role.append("maintenance_checklist")
    if "methodology" in t or "evaluation" in t or "assessment" in t:
        reasoning_role.append("evaluation_methodology")

    preferred_chunk_types: list[str] = []
    if re.search(r"\b(table of contents|contents)\b", text, flags=re.IGNORECASE):
        preferred_chunk_types.append("toc")
    if "table" in t and "fault" in t:
        preferred_chunk_types.append("fault_table")
    if "procedure" in t or "step" in t:
        preferred_chunk_types.append("procedure")
    if "checklist" in t:
        preferred_chunk_types.append("checklist")
    if "definition" in t:
        preferred_chunk_types.append("definition")
    if "equation" in t:
        preferred_chunk_types.append("equation")
    if "case" in t and "example" in t:
        preferred_chunk_types.append("case_example")
    preferred_chunk_types.append("general_section")

    # Dedup
    equipment = [x for i, x in enumerate(equipment) if x in EQUIPMENT_SCOPE_ALLOWED and x not in equipment[:i]]
    fault_types = [x for i, x in enumerate(fault_types) if x in FAULT_TYPES_ALLOWED and x not in fault_types[:i]]
    topics = [x for i, x in enumerate(topics) if x in CANONICAL_TOPICS_ALLOWED and x not in topics[:i]]
    reasoning_role = [x for i, x in enumerate(reasoning_role) if x in REASONING_ROLE_ALLOWED and x not in reasoning_role[:i]]
    preferred_chunk_types = [
        x
        for i, x in enumerate(preferred_chunk_types)
        if x in PREFERRED_CHUNK_TYPES_ALLOWED and x not in preferred_chunk_types[:i]
    ]

    return equipment, fault_types, topics, reasoning_role, preferred_chunk_types


DOMAIN_HINTS = {
    "fault",
    "faults",
    "faulted",
    "diagnostic",
    "diagnostics",
    "diagnosis",
    "troubleshooting",
    "alarm",
    "alarms",
    "symptom",
    "cause",
    "causes",
    "test",
    "tests",
    "setpoint",
    "temperature",
    "pressure",
    "airflow",
    "economizer",
    "mixed",
    "supply",
    "return",
    "outside",
    "damper",
    "valve",
    "coil",
    "sensor",
    "calibration",
    "commissioning",
    "maintenance",
    "sequence",
    "operation",
}


STRONG_HINTS = {
    "fault",
    "faults",
    "diagnostic",
    "diagnostics",
    "diagnosis",
    "troubleshooting",
    "alarm",
    "alarms",
    "symptom",
    "cause",
    "causes",
    "setpoint",
    "temperature",
    "pressure",
    "airflow",
    "economizer",
    "damper",
    "valve",
    "coil",
    "sensor",
    "leakage",
    "calibration",
}


STRONG_PHRASES = {
    "sequence of operations",
    "sequence of operation",
    "mixed air",
    "air handling unit",
    "supply air",
    "return air",
    "outside air",
    "supply air temperature",
    "discharge air temperature",
    "outdoor air temperature",
    "static pressure",
    "pressure setpoint",
    "temperature reset",
}


STOPWORDS = {
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "for",
    "a",
    "an",
    "on",
    "with",
    "by",
    "as",
    "at",
    "from",
    "this",
    "that",
    "is",
    "are",
    "be",
    "been",
    "will",
    "shall",
}


def tokenize_words(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z\-']+", text.lower())
    return [w for w in words if w not in STOPWORDS]


def is_good_query_phrase(phrase: str) -> bool:
    p = normalize_ws(phrase)
    if not p:
        return False
    if is_boilerplate_line(p):
        return False
    # Must contain at least one domain hint word
    words = tokenize_words(p)
    if not any(w in DOMAIN_HINTS for w in words):
        return False

    # Require strong diagnostic/fault language, unless it is the known strong phrase.
    strong_count = sum(1 for w in words if w in STRONG_HINTS)
    if strong_count == 0 and p.lower() not in STRONG_PHRASES:
        return False
    # Avoid phrases dominated by numbers/codes
    if looks_like_doc_code(p):
        return False
    if len(p) > 80:
        return False
    if len(words) < 2:
        return False
    return True


def extract_glossary_terms(pages_text: list[str], max_pages: int = 40) -> list[str]:
    # Evidence-only: look for a page containing 'Glossary' heading and then parse
    # term-like lines ("TERM — definition" or "TERM: definition").
    for i, page in enumerate(pages_text[:max_pages]):
        if re.search(r"\bglossary\b", page, flags=re.IGNORECASE):
            blob = "\n".join(pages_text[i : i + 3])
            terms: list[str] = []
            for raw in blob.splitlines():
                line = normalize_ws(raw)
                if not line:
                    continue
                if is_boilerplate_line(line):
                    continue
                m = re.match(r"^([A-Za-z][A-Za-z0-9\-/ ]{2,40})\s*[:\-–—]\s+", line)
                if m:
                    term = normalize_ws(m.group(1))
                    term = term.strip("-–— ")
                    if 3 <= len(term) <= 45:
                        terms.append(term)
            # de-dup
            seen: set[str] = set()
            uniq: list[str] = []
            for t in terms:
                tl = t.lower()
                if tl in seen:
                    continue
                seen.add(tl)
                uniq.append(t)
            return uniq
    return []


def extract_domain_phrases_from_ngrams(pages_text: list[str], max_pages: int = 40) -> list[str]:
    # Evidence-only: mine repeated 2-5 word phrases containing domain hints.
    # This avoids TOC noise and pulls diagnostic language when present.
    text = "\n".join(pages_text[:max_pages])
    text = re.sub(r"\s+", " ", text)
    words = tokenize_words(text)
    if not words:
        return []

    counts: Counter[str] = Counter()
    for n in (2, 3, 4, 5):
        for i in range(0, len(words) - n + 1):
            ng = words[i : i + n]
            if not any(w in DOMAIN_HINTS for w in ng):
                continue
            phrase = " ".join(ng)
            if len(phrase) > 80:
                continue
            # Filter obvious boilerplate fragments
            if is_boilerplate_line(phrase):
                continue
            counts[phrase] += 1

    # Prefer phrases that repeat (>=2), otherwise top domain phrases
    candidates = [p for p, c in counts.most_common() if c >= 2]
    if len(candidates) < 10:
        candidates = [p for p, _ in counts.most_common(50)]

    # De-dup and keep good phrases
    uniq: list[str] = []
    seen: set[str] = set()
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        if is_good_query_phrase(p):
            uniq.append(p)
    return uniq


def build_retrieval_queries(key_sections: list[str], heading_lines: list[str], pages_text: list[str]) -> list[str]:
    # Only from headings/glossary/repeated phrases/tables. Here we use:
    # - key_sections (TOC headings)
    # - explicit repeated phrases in first pages (top bigrams with HVAC-ish tokens)
    queries: list[str] = []

    for s in key_sections:
        ss = normalize_ws(s)
        if is_good_query_phrase(ss):
            queries.append(ss)

    for h in heading_lines[:30]:
        hh = normalize_ws(h)
        if is_good_query_phrase(hh):
            queries.append(hh)

    # Table labels are explicit, useful retrieval anchors.
    for page in pages_text[:15]:
        for raw in page.splitlines():
            line = normalize_ws(raw)
            if re.match(r"^table\s+\d+", line, flags=re.IGNORECASE):
                if is_good_query_phrase(line):
                    # Keep the label only when it contains diagnostic-domain language.
                    queries.append(line)

    # Extract some explicit phrases from first pages, without inventing.
    blob = "\n".join(pages_text[:8])
    blob = re.sub(r"\s+", " ", blob)
    blob_l = blob.lower()

    # Candidate explicit terms (must appear in blob)
    explicit_terms = [
        "economizer",
        "mixed air",
        "air handling unit",
        "sequence of operations",
        "troubleshooting",
        "maintenance",
        "commissioning",
        "fault detection",
        "diagnostics",
        "installation",
        "operation",
        "startup",
        "inspection",
        "alarm",
        "sensor drift",
        "stuck damper",
    ]
    for term in explicit_terms:
        if term in blob_l:
            if is_good_query_phrase(term) or term in STRONG_PHRASES:
                queries.append(term)

    # Add glossary terms (if available) and repeated domain phrases.
    for term in extract_glossary_terms(pages_text, max_pages=50)[:20]:
        if is_good_query_phrase(term):
            queries.append(term)
    for phrase in extract_domain_phrases_from_ngrams(pages_text, max_pages=60)[:30]:
        if is_good_query_phrase(phrase):
            queries.append(phrase)

    # Clean and keep 6-12, preserve order, de-dup
    seen: set[str] = set()
    uniq: list[str] = []
    for q in queries:
        qn = normalize_ws(q)
        if not qn:
            continue
        qn = qn.strip("-•")
        if qn.lower() in seen:
            continue
        seen.add(qn.lower())
        uniq.append(qn)

    # Ensure count range by trimming; if too short, return as-is.
    return uniq[:12]


def infer_reasoning_roles(doc_type: str) -> list[str]:
    # Ensure at least one role, using document category as a conservative proxy.
    if doc_type in {"guideline"}:
        return ["fault_condition_definition", "evaluation_methodology"]
    if doc_type in {"research", "assessment_guidelines", "survey_report"}:
        return ["evaluation_methodology", "physical_behavior_explanation"]
    if doc_type in {"troubleshooting_guide"}:
        return ["diagnostic_tests", "resolution_steps"]
    if doc_type in {"iom"}:
        return ["inspection_procedure", "resolution_steps", "maintenance_checklist"]
    if doc_type in {"oem_manual"}:
        return ["inspection_procedure", "maintenance_checklist"]
    if doc_type in {"handbook"}:
        return ["physical_behavior_explanation"]
    return ["physical_behavior_explanation"]


def choose_chunking_strategy(doc_type: str, key_sections: list[str]) -> tuple[str, int | None, int | None]:
    # Recommend, not enforce.
    if key_sections:
        return "section_based", 900, 120
    if doc_type in {"research", "guideline", "assessment_guidelines"}:
        return "hybrid", 850, 120
    return "fixed_tokens", 800, 100


def supports_flags(text: str) -> tuple[bool, bool]:
    t = text.lower()
    supports_diagnosis = any(
        w in t
        for w in [
            "fault",
            "diagnostic",
            "diagnostics",
            "symptom",
            "cause",
            "troubleshooting",
            "alarm",
        ]
    )
    supports_resolution = any(w in t for w in ["procedure", "inspection", "maintenance", "corrective action", "repair"])
    return supports_diagnosis, supports_resolution


def make_doc_id(file_name: str) -> str:
    base = re.sub(r"\.[Pp][Dd][Ff]$", "", file_name)
    base = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_")
    base = re.sub(r"_+", "_", base)
    return base.upper()[:64]


@dataclass
class BuildResult:
    obj: dict
    notes: list[str]


def build_metadata_for_pdf(path: Path) -> BuildResult:
    notes: list[str] = []

    reader = PdfReader(str(path))
    pages_text = extract_text_pages(reader, max_pages=60)
    first_blob = "\n".join(pages_text)

    title, title_note = extract_title(reader, pages_text)
    if title_note:
        notes.append(f"title: {title_note}")

    authority, auth_note = extract_authority(pages_text)
    if auth_note:
        notes.append(f"authority: {auth_note}")

    meta_title = None
    meta = getattr(reader, "metadata", None)
    if meta:
        mt = getattr(meta, "title", None)
        if isinstance(mt, str) and mt.strip():
            meta_title = mt.strip()

    doc_type, doc_type_note = detect_doc_type(pages_text, meta_title)
    notes.append(f"doc_type: {doc_type_note}")

    version_or_revision = find_version_or_revision(first_blob)
    if version_or_revision is None:
        notes.append("version_or_revision: No explicit 'Revision/Rev/Version' marker or unambiguous date found in first pages.")

    publication_year = find_publication_year(first_blob)
    if publication_year is None:
        notes.append("publication_year: No single explicit year uniquely identifiable in first pages (or multiple years found).")

    language = guess_language(first_blob)
    if language is None:
        notes.append("language: Unable to confidently infer language.")

    key_sections, ks_note = extract_key_sections(reader, pages_text)
    if ks_note:
        notes.append(f"key_sections: {ks_note}")

    heading_lines = extract_heading_lines(pages_text, max_pages=25)

    equipment_scope, fault_types, canonical_topics, reasoning_role, preferred_chunk_types = evidence_tags(first_blob)
    if not reasoning_role:
        reasoning_role = infer_reasoning_roles(doc_type)
        notes.append("reasoning_role: No explicit role markers found; inferred from doc_type to satisfy required non-empty field.")

    supports_diagnosis, supports_resolution = supports_flags(first_blob)

    retrieval_queries = build_retrieval_queries(key_sections, heading_lines, pages_text)
    if len(retrieval_queries) < 6:
        notes.append("retrieval_queries: Fewer than 6 evidence-grounded query phrases could be derived from headings/glossary/repeated domain phrases.")

    chunking_strategy, rec_size, rec_overlap = choose_chunking_strategy(doc_type, key_sections)

    doc_id = make_doc_id(path.name)

    ui_label = title if title else path.stem
    ui_label = ui_label[:80]

    citation_short = None
    if title and authority:
        citation_short = f"{authority} – {title}"
    elif title:
        citation_short = title

    # Priority tier heuristic (not content hallucination; can be overridden later)
    priority_tier = 5
    if doc_type == "guideline":
        priority_tier = 1
    elif doc_type in {"research", "assessment_guidelines", "survey_report"}:
        priority_tier = 2
    elif doc_type in {"iom", "oem_manual"}:
        priority_tier = 3
    elif doc_type == "troubleshooting_guide":
        priority_tier = 4
    elif doc_type == "handbook":
        priority_tier = 5

    obj = {
        "schema_version": SCHEMA_VERSION,
        "doc_id": doc_id,
        "file_name": path.name,
        "doc_path": str(path),
        "sha256": sha256_file(path),
        "title": title,
        "authority": authority,
        "doc_type": doc_type,
        "version_or_revision": version_or_revision,
        "publication_year": publication_year,
        "language": language,
        "equipment_scope": equipment_scope,
        "fault_types": fault_types,
        "canonical_topics": canonical_topics,
        "reasoning_role": reasoning_role,
        "supports_diagnosis": bool(supports_diagnosis),
        "supports_resolution": bool(supports_resolution),
        "key_sections": key_sections,
        "retrieval_queries": retrieval_queries,
        "preferred_chunk_types": preferred_chunk_types,
        "chunking_strategy": chunking_strategy,
        "recommended_chunk_size_tokens": rec_size,
        "recommended_overlap_tokens": rec_overlap,
        "ui_label": ui_label,
        "citation_short": citation_short,
        "citation_full": None,
        "priority_tier": priority_tier,
        "extraction_notes": " ".join(notes),
    }

    # Sanity: enforce allowed values
    assert obj["doc_type"] in DOC_TYPE_ALLOWED
    assert obj["chunking_strategy"] in CHUNKING_STRATEGY_ALLOWED
    for x in obj["equipment_scope"]:
        assert x in EQUIPMENT_SCOPE_ALLOWED
    for x in obj["fault_types"]:
        assert x in FAULT_TYPES_ALLOWED
    for x in obj["canonical_topics"]:
        assert x in CANONICAL_TOPICS_ALLOWED
    for x in obj["reasoning_role"]:
        assert x in REASONING_ROLE_ALLOWED
    for x in obj["preferred_chunk_types"]:
        assert x in PREFERRED_CHUNK_TYPES_ALLOWED

    return BuildResult(obj=obj, notes=notes)


def flatten_list(value: object) -> str:
    if isinstance(value, list):
        return "|".join(str(x) for x in value)
    return "" if value is None else str(value)


def main() -> None:
    manuals_dir = Path(r"e:\dissertation-project\agentic-fault-gpt\knowledge\manual")
    pdfs = sorted(manuals_dir.glob("*.pdf"))

    docs: list[dict] = []
    for pdf in pdfs:
        docs.append(build_metadata_for_pdf(pdf).obj)

    out_json = Path(r"e:\dissertation-project\agentic-fault-gpt\documents_metadata.json")
    out_csv = Path(r"e:\dissertation-project\agentic-fault-gpt\docs_manifest.csv")
    out_md = Path(r"e:\dissertation-project\agentic-fault-gpt\documents_metadata.md")

    out_json.write_text(json.dumps(docs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    fieldnames = list(docs[0].keys()) if docs else []
    if fieldnames:
        with out_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for d in docs:
                row = {k: flatten_list(v) for k, v in d.items()}
                writer.writerow(row)
    else:
        out_csv.write_text("", encoding="utf-8")

    # Markdown summary table
    header_cols = [
        "doc_id",
        "ui_label",
        "doc_type",
        "authority",
        "equipment_scope",
        "fault_types",
        "reasoning_role",
        "priority_tier",
    ]

    lines: list[str] = []
    lines.append("# Documents Metadata Summary\n")
    lines.append("This file is derived ONLY from local PDF text extraction. Fields are null when not explicitly present in the PDFs.\n")

    if not docs:
        lines.append("No PDFs found in knowledge/manual.\n")
    else:
        lines.append("| " + " | ".join(header_cols) + " |")
        lines.append("| " + " | ".join(["---"] * len(header_cols)) + " |")
        for d in docs:
            row = []
            for col in header_cols:
                val = d.get(col)
                if isinstance(val, list):
                    row.append(" ".join(val) if val else "")
                else:
                    row.append("" if val is None else str(val))
            lines.append("| " + " | ".join(row) + " |")

        lines.append("\n## Extraction Notes\n")
        for d in docs:
            lines.append(f"- **{d['doc_id']}**: {d.get('extraction_notes','')}")

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
