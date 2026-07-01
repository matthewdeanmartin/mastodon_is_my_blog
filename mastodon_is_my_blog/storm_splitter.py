from __future__ import annotations

import re

_COUNTER_SUFFIX_LEN = 7  # " (n/N)" single-digit worst case; grows for 10+ chunks


def storm_split(
    text: str,
    max_chars: int = 500,
    add_counter: bool = False,
) -> list[str]:
    """Split text into chunks ≤ max_chars using paragraph then sentence boundaries."""
    text = text.strip()
    if not text:
        return []

    segments = _to_segments(text)

    if not add_counter:
        return _greedy_pack(segments, max_chars)

    # The counter suffix width depends on the chunk count, which depends on the
    # budget. Repack with a wider suffix until the actual suffix fits: shrinking
    # the budget only ever increases the chunk count, so this converges.
    suffix_len = _COUNTER_SUFFIX_LEN
    while True:
        chunks = _greedy_pack(segments, max_chars - suffix_len)
        total = len(chunks)
        needed = len(f" ({total}/{total})")
        if needed <= suffix_len:
            break
        suffix_len = needed

    if total <= 1:
        return chunks

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


def _hard_split(segment: str, budget: int) -> list[str]:
    """Split an over-budget segment on word boundaries, then raw slices."""
    pieces: list[str] = []
    current = ""
    for word in segment.split():
        while len(word) > budget:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(word[:budget])
            word = word[budget:]
        joined = current + " " + word if current else word
        if len(joined) <= budget:
            current = joined
        else:
            pieces.append(current)
            current = word
    if current:
        pieces.append(current)
    return pieces


def _greedy_pack(segments: list[str], budget: int) -> list[str]:
    budget = max(budget, 1)
    chunks: list[str] = []
    current = ""
    for seg in segments:
        if len(seg) > budget:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(_hard_split(seg.strip(), budget))
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
