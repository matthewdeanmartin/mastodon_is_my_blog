import logging
import re
from html import unescape
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from mastodon_is_my_blog.data.domain_categories import DOMAIN_CONFIG

TAG_JOBS_KEYWORDS: frozenset[str] = frozenset([
    "hiring", "job", "jobs", "jobhunting", "jobsearch",
    "getfedihired", "fedihired", "career", "careers", "recruitment", "recruiter",
])

STRONG_JOB_PHRASES: tuple[str, ...] = (
    "we're hiring", "we are hiring", "now hiring", "join our team",
    "job listing", "job post", "job opening", "open position",
    "open role", "apply now", "apply here", "submit your application",
    "send your cv", "send your resume",
)

WEAK_JOB_KEYWORDS: tuple[str, ...] = (
    "hiring", "recruiter", "freelance", "contract", "full-time", "part-time",
)

logger = logging.getLogger(__name__)

# Mastodon post URLs follow the pattern /@username/numeric_id
# e.g. https://mastodon.social/@gargron/112345678901234567
MASTODON_POST_URL_RE = re.compile(r"^/@[\w.]+/\d+$")

# --- Helper: Content Analysis ---
def analyze_content_domains(
    html: str, media_attachments: list, is_reply_to_other: bool, tags: list | None = None
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
        "has_job": False,
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
                # Mastodon quote-posts use /@user/id URLs â€” not generic links
                parsed_path = urlparse(link["href"]).path
                is_mastodon_post = bool(MASTODON_POST_URL_RE.match(parsed_path))
                if not is_mastodon_post:
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

            # Check Jobs (job board domains)
            if any(d in clean_domain for d in DOMAIN_CONFIG["jobs"]):
                flags["has_job"] = True

        except Exception as e:
            logger.error("Error analyzing content: %s", e)
            continue

    # Check for Questions (words ending with ?)
    text_content = soup.get_text()

    if not is_reply_to_other and re.search(r"\w+\?", text_content):
        flags["has_question"] = has_human_question(text_content)

    # Job detection (text-based) — only if not already flagged by domain
    if not flags["has_job"]:
        lower_text = text_content.lower()
        # Tier 1: job hashtags
        if tags:
            lower_tags = [t.lower() for t in tags]
            if any(t in TAG_JOBS_KEYWORDS for t in lower_tags):
                flags["has_job"] = True
        # Tier 1: strong phrases
        if not flags["has_job"] and any(p in lower_text for p in STRONG_JOB_PHRASES):
            flags["has_job"] = True
        # Tier 3: two or more weak signals
        if not flags["has_job"]:
            weak_hits = sum(1 for kw in WEAK_JOB_KEYWORDS if kw in lower_text)
            if weak_hits >= 2:
                flags["has_job"] = True

    return flags


def has_human_question(html: str) -> bool:
    # drop tags
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)

    # drop URLs (now visible after tag strip)
    text = re.sub(r"https?://\S+", " ", text)

    # question heuristic: word char before ?, not part of token junk
    return bool(re.search(r"\b[\w’']+\?\s*$|\b[\w’']+\?\s+", text))
