"""Unit tests for storm_splitter.

The author persona depends on every chunk fitting under the instance's
character limit: chunks are posted verbatim by publish_draft, and any
over-limit chunk fails with a 422 mid-storm.
"""

from hypothesis import given
from hypothesis import strategies as st

from mastodon_is_my_blog.storm_splitter import storm_split


def test_empty_text_returns_no_chunks():
    assert storm_split("") == []
    assert storm_split("   \n\n  ") == []


def test_short_text_is_single_chunk_without_counter():
    text = "Just one short thought."
    assert storm_split(text, max_chars=500) == [text]


def test_single_chunk_never_gets_counter():
    text = "Just one short thought."
    assert storm_split(text, max_chars=500, add_counter=True) == [text]


def test_splits_on_paragraph_boundaries():
    text = "First paragraph here.\n\nSecond paragraph here."
    chunks = storm_split(text, max_chars=25)
    assert chunks == ["First paragraph here.", "Second paragraph here."]


def test_splits_on_sentence_boundaries():
    text = "One sentence. Two sentence. Red sentence. Blue sentence."
    chunks = storm_split(text, max_chars=30)
    assert all(len(c) <= 30 for c in chunks)
    assert " ".join(chunks) == text


def test_counter_format():
    text = "Alpha alpha alpha. Beta beta beta. Gamma gamma gamma."
    chunks = storm_split(text, max_chars=25, add_counter=True)
    total = len(chunks)
    assert total > 1
    for i, chunk in enumerate(chunks):
        assert chunk.endswith(f"({i + 1}/{total})")


def test_counter_chunks_respect_max_chars_with_ten_or_more_chunks():
    """Regression: ' (10/12)' is 8 chars, not the 7 originally budgeted,
    so storms of 10+ posts used to exceed max_chars and get rejected."""
    sentences = [f"Sentence number {i} pads out to something real." for i in range(30)]
    text = " ".join(sentences)
    chunks = storm_split(text, max_chars=100, add_counter=True)
    assert len(chunks) >= 10
    for chunk in chunks:
        assert len(chunk) <= 100, f"{len(chunk)} chars: {chunk!r}"


def test_oversized_sentence_is_hard_split():
    """Regression: a single sentence longer than max_chars used to be
    emitted whole, producing an unpostable chunk."""
    text = "word " * 300  # one 'sentence', ~1500 chars
    chunks = storm_split(text.strip(), max_chars=500)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 500


def test_oversized_unbroken_token_is_hard_split():
    text = "x" * 1200
    chunks = storm_split(text, max_chars=500)
    assert all(len(c) <= 500 for c in chunks)
    assert "".join(chunks) == text


@given(
    text=st.text(
        alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
        min_size=0,
        max_size=2000,
    ),
    max_chars=st.integers(min_value=20, max_value=500),
    add_counter=st.booleans(),
)
def test_no_chunk_ever_exceeds_max_chars(text, max_chars, add_counter):
    chunks = storm_split(text, max_chars=max_chars, add_counter=add_counter)
    for chunk in chunks:
        assert len(chunk) <= max_chars
        assert chunk.strip()


@given(text=st.text(alphabet="abcdefg .!?\n", min_size=1, max_size=1000))
def test_no_characters_are_lost(text):
    # Hard-splitting may break a >100-char run mid-word, but no
    # non-whitespace character may ever be dropped or reordered.
    chunks = storm_split(text, max_chars=100)
    assert "".join("".join(chunks).split()) == "".join(text.split())
