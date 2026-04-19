from __future__ import annotations

import re

_COUNTER_SUFFIX_LEN = 7  # " (n/N)" worst case


def storm_split(
    text: str,
    max_chars: int = 500,
    add_counter: bool = False,
) -> list[str]:
    """Split text into chunks ≤ max_chars using paragraph then sentence boundaries."""
    text = text.strip()
    if not text:
        return []

    budget = max_chars - _COUNTER_SUFFIX_LEN if add_counter else max_chars
    segments = _to_segments(text)
    chunks = _greedy_pack(segments, budget)

    if not add_counter or len(chunks) <= 1:
        return chunks

    total = len(chunks)
    return [f"{chunk} ({i + 1}/{total})" for i, chunk in enumerate(chunks)]


def _to_segments(text: str) -> list[str]:
    segments: list[str] = []
    paragraphs = re.split(r"\n{2,}", text)
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        sentences = _split_sentences(para)
        segments.extend(s for s in sentences if s)
    return segments or [text.strip()]


def _split_sentences(text: str) -> list[str]:
    # Split after sentence-ending punctuation followed by whitespace or end
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _greedy_pack(segments: list[str], budget: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for seg in segments:
        if len(seg) > budget:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.append(seg.strip())
            continue
        joined = current + " " + seg if current else seg
        if len(joined) <= budget:
            current = joined
        else:
            if current:
                chunks.append(current.strip())
            current = seg
    if current.strip():
        chunks.append(current.strip())
    return chunks
