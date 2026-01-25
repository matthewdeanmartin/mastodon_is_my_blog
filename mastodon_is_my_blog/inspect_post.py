import re
from html import unescape
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from mastodon_is_my_blog.data.domain_categories import DOMAIN_CONFIG

# Schema for DOMAIN_CONFIG
# DOMAIN_CONFIG = {
#     "video": {
#         "youtube.com",
#     },
#     "picture": {
#         "flickr.com",
#     },
#     "tech": {
#         "github.com",
#     },
#     "news": {
#         "nytimes.com",
#     },
# }


# --- Helper: Content Analysis ---
def analyze_content_domains(
    html: str, media_attachments: list, is_reply_to_other: bool
) -> dict:
    """
    Analyzes HTML content and attachments to determine content flags.
    Returns dict of boolean flags.
    """
    soup = BeautifulSoup(html, "html.parser")

    flags = {
        "has_media": len(media_attachments) > 0,
        "has_video": False,
        "has_news": False,
        "has_tech": False,
        "has_link": False,
        "has_question": False,
    }

    # Check Attachments
    for m in media_attachments:
        if m["type"] in ["video", "gifv", "audio"]:
            flags["has_video"] = True
        if m["type"] == "image":
            flags["has_media"] = True

    # Check Links (<a> tags and <iframe>)
    if soup.find("iframe"):
        flags["has_video"] = True

    for link in soup.find_all("a", href=True):
        try:
            # Check classes to distinguish generic links from Mentions/Hashtags
            # Mastodon mentions/tags usually have class="mention" or "hashtag"
            classes = link.get("class", [])
            is_mention_or_tag = "mention" in classes or "hashtag" in classes

            if not is_mention_or_tag:
                flags["has_link"] = True

            domain = urlparse(link["href"]).netloc.lower()
            # Remove 'www.' prefix if present for matching
            clean_domain = domain.replace("www.", "")

            # Check Video
            if any(d in clean_domain for d in DOMAIN_CONFIG["video"]):
                flags["has_video"] = True

            # Check Pictures (External)
            if any(d in clean_domain for d in DOMAIN_CONFIG["picture"]):
                flags["has_media"] = True  # Treat external image links as "has_media"

            # Check Tech
            if any(d in clean_domain for d in DOMAIN_CONFIG["tech"]):
                flags["has_tech"] = True

            # Check News
            if any(d in clean_domain for d in DOMAIN_CONFIG["news"]):
                flags["has_news"] = True

        except Exception:
            logger.error(e)
            continue

    # Check for Questions (words ending with ?)
    # Extract text content and check for question marks
    text_content = soup.get_text()
    # Look for word boundaries followed by question marks

    # fails with URLS eg example.com?foo
    # if re.search(r"\w+\?", text_content):
    #     flags["has_question"] = True

    # Question to self are fine, that's a long question
    # Questions to others is a discussion, not a request for help from the general public
    if not is_reply_to_other and re.search(r"\w+\?", text_content):
        flags["has_question"] = has_human_question(text_content)

    return flags


def has_human_question(html: str) -> bool:
    # drop tags
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)

    # drop URLs (now visible after tag strip)
    text = re.sub(r"https?://\S+", " ", text)

    # question heuristic: word char before ?, not part of token junk
    return bool(re.search(r"\b[\w’']+\?\s*$|\b[\w’']+\?\s+", text))
