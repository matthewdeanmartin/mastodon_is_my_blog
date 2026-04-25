"""
Topic extraction helpers for the Forum feature (Option B).

Uses spaCy for POS-filtered lemmatization and wordfreq for Zipf-based
rarity filtering. The spaCy model must be loaded once at app startup
and passed in as `nlp`; all functions accept it as a parameter so
FastAPI's app.state.nlp can be injected without module-level globals.
"""

import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup


@dataclass
class Token:
    lemma: str
    pos: str
    zipf: float


def strip_html(s: str) -> str:
    return BeautifulSoup(s, "html.parser").get_text(separator=" ")


def tokens(doc_text: str, nlp: Any) -> list[Token]:
    """spaCy-lemmatized tokens, POS-filtered to NOUN/PROPN/ADJ, Zipf attached."""
    from wordfreq import zipf_frequency

    keep_pos = {"NOUN", "PROPN", "ADJ"}
    clean = strip_html(doc_text)
    doc = nlp(clean)
    result: list[Token] = []
    for tok in doc:
        if tok.pos_ not in keep_pos:
            continue
        if not tok.is_alpha:
            continue
        lemma = tok.lemma_.lower()
        if len(lemma) < 3:
            continue
        z = zipf_frequency(lemma, "en")
        result.append(Token(lemma=lemma, pos=tok.pos_, zipf=z))
    return result


def uncommon_lemmas(doc_text: str, nlp: Any, zipf_max: float = 4.0, min_len: int = 4) -> list[str]:
    """Deduped lemmas with wordfreq Zipf <= zipf_max and minimum length."""
    seen: set[str] = set()
    result: list[str] = []
    for tok in tokens(doc_text, nlp):
        if tok.zipf > zipf_max:
            continue
        if len(tok.lemma) < min_len:
            continue
        if tok.lemma not in seen:
            seen.add(tok.lemma)
            result.append(tok.lemma)
    return result


def entities(doc_text: str, nlp: Any) -> list[str]:
    """spaCy NER: PERSON, ORG, PRODUCT, WORK_OF_ART, EVENT, GPE."""
    keep_labels = {"PERSON", "ORG", "PRODUCT", "WORK_OF_ART", "EVENT", "GPE"}
    clean = strip_html(doc_text)
    doc = nlp(clean)
    seen: set[str] = set()
    result: list[str] = []
    for ent in doc.ents:
        if ent.label_ in keep_labels:
            text = ent.text.strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
    return result


def thread_topics(texts: list[str], nlp: Any, top_k: int = 5) -> list[str]:  # pylint: disable=unused-argument
    """TF-IDF over thread posts vs background corpus, return top_k terms."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    if not texts:
        return []

    cleaned = [strip_html(t) for t in texts]

    # Use sublinear TF and English stop words as a baseline
    vectorizer = TfidfVectorizer(
        max_features=200,
        sublinear_tf=True,
        stop_words="english",
        token_pattern=r"[a-zA-Z]{4,}",
    )
    try:
        tfidf = vectorizer.fit_transform(cleaned)
    except ValueError:
        return []

    # Sum TF-IDF scores across all docs in the thread
    scores = tfidf.sum(axis=0).A1
    feature_names = vectorizer.get_feature_names_out()
    top_indices = scores.argsort()[::-1][:top_k]
    return [feature_names[i] for i in top_indices]


def load_spacy_model():
    """Load and return the en_core_web_sm model. Call once at startup."""
    import spacy

    return spacy.load("en_core_web_sm", disable=["parser", "ner"])


_STOPWORDS = re.compile(
    r"\b(?:the|be|to|of|and|a|in|that|have|it|for|not|on|with|he|as|you|do|at|this|but|his|by|from|they|we|say|her|she|or|an|will|my|one|all|would|there|their|what|so|up|out|if|about|who|get|which|go|me|when|make|can|like|time|no|just|him|know|take|people|into|year|your|good|some|could|them|see|other|than|then|now|look|only|come|its|over|think|also|back|after|use|two|how|our|work|first|well|way|even|new|want|because|any|these|give|most|us)\b",
    re.IGNORECASE,
)
