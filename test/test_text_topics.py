"""Tests for text_topics (forum topic extraction).

Uses a fake spaCy pipeline so no model download is needed; wordfreq and
scikit-learn are real project dependencies and are exercised directly.
"""

from dataclasses import dataclass, field

from mastodon_is_my_blog.text_topics import (
    entities,
    strip_html,
    thread_topics,
    tokens,
    uncommon_lemmas,
)


@dataclass
class FakeTok:
    lemma_: str
    pos_: str = "NOUN"
    is_alpha: bool = True


@dataclass
class FakeEnt:
    text: str
    label_: str


@dataclass
class FakeDoc:
    toks: list[FakeTok] = field(default_factory=list)
    ents: list[FakeEnt] = field(default_factory=list)

    def __iter__(self):
        return iter(self.toks)


class FakeNlp:
    """Callable standing in for a spaCy pipeline."""

    def __init__(self, doc: FakeDoc | None = None):
        self.doc = doc or FakeDoc()
        self.seen: list[str] = []

    def __call__(self, text: str) -> FakeDoc:
        self.seen.append(text)
        return self.doc


class TestStripHtml:
    def test_removes_tags_and_keeps_text(self):
        assert strip_html("<p>alpha <b>beta</b></p>").split() == ["alpha", "beta"]

    def test_plain_text_passthrough(self):
        assert strip_html("no markup here") == "no markup here"


class TestTokens:
    def test_filters_pos_alpha_and_length(self):
        doc = FakeDoc(
            toks=[
                FakeTok("mountain", "NOUN"),
                FakeTok("run", "VERB"),  # wrong POS
                FakeTok("x9", "NOUN", is_alpha=False),  # not alpha
                FakeTok("ox", "NOUN"),  # too short (<3)
                FakeTok("Purple", "ADJ"),
            ]
        )
        result = tokens("whatever", FakeNlp(doc))
        assert [t.lemma for t in result] == ["mountain", "purple"]

    def test_html_is_stripped_before_nlp(self):
        nlp = FakeNlp()
        tokens("<p>hello world</p>", nlp)
        assert "<p>" not in nlp.seen[0]
        assert "hello" in nlp.seen[0]

    def test_zipf_attached(self):
        doc = FakeDoc(toks=[FakeTok("house", "NOUN")])
        (tok,) = tokens("x", FakeNlp(doc))
        assert tok.zipf > 4.0  # 'house' is a common English word


class TestUncommonLemmas:
    def test_common_words_excluded_rare_kept_deduped(self):
        doc = FakeDoc(
            toks=[
                FakeTok("house", "NOUN"),  # common → excluded
                FakeTok("zymurgy", "NOUN"),  # rare → kept
                FakeTok("zymurgy", "NOUN"),  # duplicate → deduped
                FakeTok("qat", "NOUN"),  # rare but len < 4 → excluded
            ]
        )
        assert uncommon_lemmas("x", FakeNlp(doc)) == ["zymurgy"]

    def test_empty_doc(self):
        assert uncommon_lemmas("x", FakeNlp()) == []


class TestEntities:
    def test_keeps_wanted_labels_dedupes(self):
        doc = FakeDoc(
            ents=[
                FakeEnt("Ada Lovelace", "PERSON"),
                FakeEnt("Ada Lovelace", "PERSON"),
                FakeEnt("London", "GPE"),
                FakeEnt("Tuesday", "DATE"),  # unwanted label
                FakeEnt("   ", "ORG"),  # blank text
            ]
        )
        assert entities("x", FakeNlp(doc)) == ["Ada Lovelace", "London"]


class TestThreadTopics:
    def test_empty_input(self):
        assert thread_topics([], None) == []

    def test_stopword_only_input_returns_empty(self):
        assert thread_topics(["the and of to", "a in that"], None) == []

    def test_distinctive_terms_surface(self):
        texts = [
            "The zoning board rejected the greenhouse variance again.",
            "Our greenhouse tomatoes disagree with the zoning board.",
            "<p>More greenhouse drama at the zoning meeting.</p>",
        ]
        topics = thread_topics(texts, None, top_k=5)
        assert "greenhouse" in topics
        assert "zoning" in topics
