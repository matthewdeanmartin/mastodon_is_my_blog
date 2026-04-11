from mastodon_is_my_blog.inspect_post import analyze_content_domains, has_human_question


def test_has_human_question_ignores_question_marks_inside_urls() -> None:
    html = '<p>See https://example.com/search?q=test for details.</p>'

    assert has_human_question(html) is False


def test_analyze_content_domains_sets_flags_from_links_media_and_question() -> None:
    html = """
    <p>
        Should we ship this?
        <a href="https://github.com/octocat/Hello-World">repo</a>
        <a href="https://www.reuters.com/world/">news</a>
        <a href="https://imgur.com/gallery/demo">gallery</a>
    </p>
    """
    media_attachments = [{"type": "audio"}, {"type": "image"}]

    flags = analyze_content_domains(
        html=html, media_attachments=media_attachments, is_reply_to_other=False
    )

    assert flags == {
        "has_media": True,
        "has_video": True,
        "has_news": True,
        "has_tech": True,
        "has_link": True,
        "has_question": True,
    }


def test_analyze_content_domains_ignores_mentions_hashtags_and_quote_posts() -> None:
    html = """
    <p>
        <a class="mention" href="https://mastodon.social/@alice">@alice</a>
        <a class="hashtag" href="https://mastodon.social/tags/python">#python</a>
        <a href="https://mastodon.social/@bob/112345678901234567">quoted post</a>
    </p>
    """

    flags = analyze_content_domains(
        html=html, media_attachments=[], is_reply_to_other=False
    )

    assert flags["has_link"] is False
    assert flags["has_question"] is False
    assert flags["has_media"] is False
    assert flags["has_video"] is False


def test_analyze_content_domains_skips_question_flag_for_replies() -> None:
    html = "<p>Can you review this?</p>"

    flags = analyze_content_domains(
        html=html, media_attachments=[], is_reply_to_other=True
    )

    assert flags["has_question"] is False
